"""fomc: command-line entry point.  Run `fomc --help`, or see docs/WORKFLOW.md.

Free stages (no API key):  collect, market, events, baselines, evaluate, backtest, run
LLM stages (your key):     key, llm-estimate, llm-pilot, llm-submit, llm-collect, llm-sync, audit
Team labels:               label-sample, label-report (label in the dashboard: Research > Label)
Presenting:                slides (the Story page as PowerPoint and an outline)
Tools:                     serve, doctor, export, status
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import (
    align,
    collect,
    db,
    dictionary,
    embeddings,
    fed,
    finetune,
    labels,
    market,
    policy,
    roberta,
    store,
    supervised,
)
from .config import DATA, INTERIM, LLM_DIR, PROCESSED, RESULTS, ensure_dirs, settings

PRIMARY = {"method_prefix": "llm:", "doc_types": ["minutes", "speech"], "entry": "etf_entry_next", "hold": 5}
DOC_GROUPS = [["statement"], ["minutes"], ["presser"], ["speech"], ["minutes", "speech"]]
TYPES = ["statement", "minutes", "presser", "speech"]
WORDS_TO_TOKENS = 1.35  # offline approximation when no key is configured


def _con():
    con = db.connect()
    db.init(con)
    return con


def _decision_ids(con=None) -> set[str]:
    """Statements that announce a policy decision; the rest are notices (swap lines, framework reviews)."""
    own = con is None
    con = con or _con()
    ids = {r[0] for r in con.execute("SELECT doc_id FROM decisions WHERE action IS NOT NULL")}
    if own:
        con.close()
    return ids


def _sample(docs: pd.DataFrame, n: int, types: list[str]) -> pd.DataFrame:
    """Evenly spaced documents per type (deterministic), for pilots and estimates."""
    parts, per = [], max(1, math.ceil(n / len(types)))
    for t in types:
        sub = docs[docs.doc_type == t].sort_values("release_date")
        if len(sub):
            idx = np.unique(np.linspace(0, len(sub) - 1, min(per, len(sub))).round().astype(int))
            parts.append(sub.iloc[idx])
    return pd.concat(parts).reset_index(drop=True)


def _jobs(what: str, docs: pd.DataFrame, types: list[str]):
    from . import audit
    from .llm import scorer

    sel = docs[docs.doc_type.isin(types)]
    builders = {
        "level": lambda: scorer.level_jobs(sel),
        "anon": lambda: scorer.level_jobs(sel, anonymized=True),
        "shift": lambda: scorer.shift_jobs(docs, doc_types=tuple(types), decisions=_decision_ids()),
        "identify": lambda: audit.identify_jobs(sel),
        "sentences": lambda: scorer.sentence_jobs(supervised.load_tdw("test")["sentence"].tolist(), "tdw_test"),
        "team": lambda: _team_jobs(),
    }
    return builders[what]()


def _team_jobs():
    from .llm import scorer

    con = _con()
    items = db.query(con, "SELECT item_id, sentence FROM label_items ORDER BY item_id")
    con.close()
    if items.empty:
        raise SystemExit("No team sentences yet: run `fomc label-sample` first.")
    return scorer.sentence_jobs(items["sentence"].tolist(), "team", ids=items["item_id"].tolist())


def _statements(con) -> pd.DataFrame:
    return db.query(
        con,
        "SELECT doc_id, meeting_date, release_date, text FROM documents "
        "WHERE doc_type = 'statement' AND note IS NULL ORDER BY release_date, doc_id",
    )


# ------------------------------------------------------------- free stages
def remember_schedule(con, upcoming: list[str]) -> list[str]:
    """Store the calendar's upcoming decision dates, and keep every date ever scheduled, the ones that have just
    passed included (the strict check asks each of them for its statement and minutes)."""

    def meta(key):
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else []

    scheduled = sorted(set(meta("scheduled_meetings")) | set(meta("upcoming_meetings")) | set(upcoming))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('upcoming_meetings', ?)", (json.dumps(upcoming),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('scheduled_meetings', ?)", (json.dumps(scheduled),))
    return upcoming


def cmd_collect(a, con):
    with db.stage(con, "collect") as d:
        idx = collect.build()
        store.save_documents(con, idx)
        members = fed.committee(
            db.query(
                con, "SELECT doc_id, release_date, url FROM documents WHERE doc_type = 'minutes' AND note IS NULL"
            ),
            db.query(con, "SELECT speaker, speaker_role, release_date FROM documents WHERE doc_type = 'speech'"),
        )
        if len(members):
            db.replace_where(con, "committee", "1 = ?", (1,), members)
            row = con.execute("SELECT value FROM meta WHERE key = 'bios'").fetchone()
            said = fed.bios(members, json.loads(row[0]) if row else None)
            con.execute("INSERT OR REPLACE INTO meta VALUES ('bios', ?)", (json.dumps(said),))
            d.update(bios=len(said))
        d.update(committee=len(members))
        upcoming = remember_schedule(con, collect.upcoming_meetings())
        con.commit()
        d.update(next_meeting=upcoming[0] if upcoming else None)
        d.update(idx.groupby("doc_type").size().to_dict(), excluded=int(idx["note"].notna().sum()))
    print(idx.groupby("doc_type").agg(n=("doc_id", "size"), excluded=("note", lambda s: s.notna().sum())))


def cmd_market(a, con):
    with db.stage(con, "market") as d:
        source = market.build()
        etf_file = PROCESSED / "etf_prices.csv"
        if not etf_file.exists():  # no fresh closes and none on file: start from the store's
            db.query(con, "SELECT * FROM etf_prices ORDER BY date").set_index("date").to_csv(etf_file)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('yield_source', ?)", (source,))
        d.update(yield_source=source)
        y, e = market.load_yields(), market.load_etfs()
        store.save_market(con, y, e)
        try:
            rates = fed.policy_rates()
            db.upsert(con, "policy_rates", rates)
            d.update(policy_rate_days=len(rates))
        except Exception as exc:  # the New York Fed API is a nice-to-have; keep the stored history
            d.update(policy_rates_error=str(exc)[:200])
        d.update(yield_days=len(y), etf_days=len(e), last=str(y.index.max().date()))
    print(f"yields {y.index.min().date()}..{y.index.max().date()} ({len(y)} days); ETFs {len(e)} days")


def cmd_events(a, con):
    with db.stage(con, "events") as d:
        ev = align.build()
        store.save_events(con, ev, market.load_yields())
        dec = policy.decisions(_statements(con))
        db.replace_where(con, "decisions", "1 = ?", (1,), dec)
        d.update(events=len(ev), decisions=int(dec["action"].notna().sum()))
    print(ev.groupby(["doc_type", "ust_window_days"]).size().unstack(fill_value=0))
    acts = dec["action"].map(policy.action_label).value_counts()
    print("decisions: " + ", ".join(f"{k} {v}" for k, v in acts.items()))


READERS = {roberta.NAME: roberta.OUT, finetune.NAME: finetune.OUT}  # references outside H1, saved as JSON


def frozen(a) -> bool:
    """After the freeze date the reported research stays as it is, whatever new data arrive (--unfreeze recomputes)."""
    import datetime

    freeze = datetime.date.fromisoformat(settings()["forward"]["freeze"])
    return datetime.date.today() > freeze and not getattr(a, "unfreeze", False)


def cmd_baselines(a, con):
    """Score every document with the three baselines and measure all readers against the human labels. After the
    freeze only new documents are scored and the validity results stay as reported: a classifier retrained on
    another machine moves in the last digits, which would rewrite a reported number."""
    from .evaluate import validity
    from .llm.scorer import texts_for

    with db.stage(con, "baselines") as d:
        docs = collect.usable()
        texts = texts_for(docs)
        hold = frozen(a)

        def todo(method):  # the documents a method still has to score
            if not hold:
                return docs
            have = set(db.query(con, "SELECT doc_id FROM scores WHERE method = ?", (method,))["doc_id"])
            return docs[~docs["doc_id"].isin(have)]

        def save(method, score):
            pending = todo(method)
            if len(pending):
                store.save_scores(con, method, score(pending), replace=not hold)
            return len(pending)

        save("dictionary", lambda ds: dictionary.score_documents(ds, texts))
        model = supervised.train()
        save("supervised", lambda ds: supervised.score_documents(model, ds, texts))
        emb = embeddings.SentenceEmbeddings().train()
        added = save("embedding", lambda ds: emb.score_documents(ds, texts))
        scores = store.load_scores(con)
        models = [m.split(":")[1] for m in scores if m.startswith("llm:")]
        extra, team, seeds = {"embedding": emb.predict}, {"embedding": emb.predict}, {}
        tdw = supervised.load_tdw("test")
        test = tdw["sentence"].tolist()
        items = db.query(con, "SELECT sentence FROM label_items ORDER BY item_id")["sentence"].tolist()
        for name, path in READERS.items():  # read once, offline, by `fomc roberta` and `fomc finetune`
            saved = roberta.test_labels(test, path)
            if saved is not None:
                extra[name] = lambda _sentences, saved=saved: saved
                runs = roberta.load(path)["tdw_test"].get("seed_labels", [])  # each seed alone, for its spread
                seeds[name] = [round(labels.macro_f1(tdw["label"], s), 4) for s in runs]
            mine = roberta.team_labels(items, path)
            if mine is not None:
                by_text = dict(zip(items, mine))
                team[name] = lambda sentences, by_text=by_text: [by_text[s] for s in sentences]
        if hold:
            con.commit()
            preds = labels.predict(con, model, team)
            d.update(frozen=settings()["forward"]["freeze"], new_documents=added, team_predictions=preds)
            print(f"frozen on {settings()['forward']['freeze']}: validity as reported; {added} new documents scored")
            return
        bench, more = validity.sentence_benchmark(model, models, extra=extra)
        db.upsert(con, "validity", bench.assign(updated_at=db.now()))
        (RESULTS / "validity_confusions.json").write_text(json.dumps(more["confusions"], indent=1))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('validity_tests', ?)", (json.dumps(more["tests"]),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('validity_confusions', ?)", (json.dumps(more["confusions"]),))
        cv = {m: json.loads((PROCESSED / f"{m}_cv.json").read_text()) for m in ("supervised", "embedding")}
        con.execute("INSERT OR REPLACE INTO meta VALUES ('baseline_cv', ?)", (json.dumps(cv),))  # for the deck
        llm = next((m for m in scores if m.startswith("llm:")), None)
        if llm:
            claude = dict(zip(scores[llm]["doc_id"], scores[llm]["score"]))
            types = dict(zip(docs["doc_id"], docs["doc_type"]))
            readers = {
                n: {**roberta.describe(claude, types, p), "seed_macro_f1": seeds.get(n, [])}
                for n, p in READERS.items()
                if p.exists()
            }
            con.execute("INSERT OR REPLACE INTO meta VALUES ('readers', ?)", (json.dumps(readers),))
        con.commit()
        d.update(methods=list(bench["method"]), team_predictions=labels.predict(con, model, team))
    print(bench.round(3).to_string(index=False))


def cmd_forecast(a, con):
    """Exploratory: does Claude's reading of the Fed add to what the market prices about the next decision?"""
    from .evaluate import forecast

    with db.stage(con, "forecast") as d:
        method = next((m for m in store.load_scores(con) if m.startswith("llm:")), None)
        if method is None:
            d.update(skipped="no Claude scores")
            print("no Claude scores yet: skipped")
            return
        res = forecast.run(con, method)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('forecast', ?)", (json.dumps(res),))
        con.commit()
        ins, oos = res["in_sample"], res["out_of_sample"]
        d.update(decisions=res["n"], p_in_sample=round(ins["p"], 4), p_real_time=round(oos["p_boot"], 4))
    print(
        f"{res['n']} decisions: R2 {ins['r2_market']:.2f} market alone, {ins['r2_both']:.2f} with tone "
        f"(F p = {ins['p']:.3f}); "
        f"real time from {oos['start']}: squared error {oos['mse_both']:.3f} with tone vs {oos['mse_market']:.3f} "
        f"(p = {oos['p_boot']:.2f})"
    )


def cmd_forward(a, con):
    """The frozen rules on data after the freeze: the pre-registered trade and the release-day direction (H2)."""
    from .evaluate import forward

    with db.stage(con, "forward") as d:
        res = forward.run(
            con,
            align.load_events(),
            store.load_scores(con),
            market.load_etfs(),
            market.load_yields(),
            _decision_ids(con),
            PRIMARY,
        )
        con.execute("INSERT OR REPLACE INTO meta VALUES ('forward', ?)", (json.dumps(res),))
        con.commit()
        s, t = res["summary"], res["tilt"]
        d.update(releases=s["releases"], hits=s["hits"], tilt_days=t.get("days"), signals=t.get("signals"))
    print(
        f"since {res['freeze']}: {s['hits']} of {s['called']} releases moved the 2-year the way the frozen rule said; "
        f"the pre-registered tilt {t.get('active_bp', 0):+.1f} bp on the portfolio over {t.get('days', 0)} days"
    )


def cmd_roberta(a, con):
    """FOMC-RoBERTa on the test sentences, statements and minutes (needs `pip install -e .[roberta]`); then rerun
    `fomc baselines` to add it to the validity table."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        raise SystemExit("FOMC-RoBERTa needs PyTorch and transformers: pip install -e .[roberta]") from None
    rec = roberta.run()
    n_test, n_docs = len(rec["tdw_test"]["labels"]), len(rec["documents"])
    print(f"{rec['model']} @ {rec['revision'][:8]} on {rec['device']}: {n_test} test sentences, {n_docs} documents")


def cmd_finetune(a, con):
    """RoBERTa fine-tuned on the TF-IDF baseline's training data (needs `pip install -e .[roberta]`; hours,
    resumable); then rerun `fomc baselines` to add it to the validity table."""
    import time

    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        raise SystemExit("Fine-tuning needs PyTorch and transformers: pip install -e .[roberta]") from None
    if not a.team:
        rec = finetune.run(log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
        c = rec["chosen"]
        print(f"{rec['model']}: epoch {c['epoch']}, CV macro-F1 {c['cv_macro_f1']:.3f}, {len(rec['documents'])} docs")
    print(f"{finetune.label_team(con)} team sentences labeled")


def cmd_evaluate(a, con):
    from . import report
    from .evaluate import event_study

    with db.stage(con, "evaluate") as d:
        scores = store.load_scores(con)
        events, yields = align.load_events(), market.load_yields()
        decisions = db.query(con, "SELECT doc_id, meeting_date, change_bp FROM decisions")
        panel = event_study.build_panel(events, yields, scores, decisions)
        panel.to_csv(RESULTS / "event_panel.csv", index=False)
        res = event_study.regress(panel, list(scores))
        db.replace_where(con, "event_study", "1 = ?", (1,), res.assign(updated_at=db.now()))
        res.to_csv(RESULTS / "event_study.csv", index=False)
        curves = event_study.response_curves(events, yields, panel, list(scores))
        db.replace_where(con, "event_curves", "1 = ?", (1,), curves)
        best = next((m for m in scores if m.startswith("llm:")), "supervised")
        main = res[(res["sample"] == "all") & (res["control"] == "none")]
        figs = [report.tone_index(scores[best], collect.usable(), yields, best), report.event_coefficients(main)]
        d.update(regressions=len(res), fdr_10=int((res["q_bh"] < 0.10).sum()), curves=len(curves), figures=figs)
    show = main[main.outcome.isin(["d2y", "pre_d2y", "drift5_d2y"])]
    print(show.pivot_table(index=["doc_type", "method", "regressor"], columns="outcome", values="t").round(2))
    print(f"{int((res['q_bh'] < 0.10).sum())} of {int(res['q_bh'].notna().sum())} main-grid tests at q < 0.10")


def cmd_backtest(a, con):
    from . import report
    from .evaluate import backtest

    with db.stage(con, "backtest") as d:
        scores = store.load_scores(con)
        events, etfs = align.load_events(), market.load_etfs()
        decisions = _decision_ids(con)
        variants = []  # (method, scores, signal, document groups)
        for method, sc in scores.items():
            if method.startswith("llmshift:"):  # Claude's own reading of the change: already a shift
                sc = sc[sc["doc_id"].isin(decisions) | ~sc["doc_id"].str.startswith("statement_")]
                covered = set(events.loc[events["doc_id"].isin(sc["doc_id"]), "doc_type"])
                variants.append((method, sc, "shift", [[t] for t in ("statement", "minutes") if t in covered]))
                continue
            variants.append((method, sc, "level", DOC_GROUPS))
            variants.append(
                (f"shift:{method}", backtest.shift_scores(sc, events, decisions), "shift", [["statement"], ["minutes"]])
            )
        rows, curves = [], {}
        for method, sc, signal, groups in variants:
            for types in groups:
                for hold in settings()["backtest"]["holding_days"]:
                    for entry in ("etf_entry", "etf_entry_next"):
                        run_id = f"{method}|{'+'.join(types)}|h{hold}|{entry}"
                        primary = (
                            method.startswith(PRIMARY["method_prefix"])
                            and types == PRIMARY["doc_types"]
                            and entry == PRIMARY["entry"]
                            and hold == PRIMARY["hold"]
                        )
                        # the pre-registered test always gets its shuffled-score placebo; the rest only on request
                        out = backtest.run(events, sc, etfs, types, hold, entry, placebo=a.placebo or primary)
                        curves[run_id] = out.pop("returns")
                        rows.append(
                            {
                                "run_id": run_id,
                                "method": method,
                                "doc_types": "+".join(types),
                                "hold": hold,
                                "entry": entry,
                                "is_primary": int(primary),
                                "signal": signal,
                                **out,
                            }
                        )
        table = backtest.deflate(pd.DataFrame(rows), curves).assign(updated_at=db.now())
        cols = [
            c
            for c in (
                "run_id",
                "method",
                "doc_types",
                "hold",
                "entry",
                "is_primary",
                "n_signals",
                "hit_rate",
                "ann_return",
                "ann_vol",
                "sharpe",
                "max_drawdown",
                "t_nw",
                "sharpe_development",
                "sharpe_holdout",
                "sharpe_post_cutoff",
                "placebo_p",
                "placebo_sharpe_95",
                "psr",
                "dsr",
                "n_trials",
                "sharpe_hurdle",
                "signal",
                "active_bp",
                "tracking_bp",
                "updated_at",
            )
            if c in table
        ]
        table = table.reindex(columns=cols)
        store.save_backtests(con, table, curves)
        table.to_csv(RESULTS / "backtest_summary.csv", index=False)
        key = f"|{'+'.join(PRIMARY['doc_types'])}|h{PRIMARY['hold']}|{PRIMARY['entry']}"
        primary_curves = {r.split("|")[0]: c for r, c in curves.items() if r.endswith(key)}
        if primary_curves:
            report.backtest_curves(
                primary_curves, None, None, "Duration tilt: minutes + speeches, next-day entry, 5-day hold", "primary"
            )
        d.update(variants=len(table))
    print(f"{len(table)} variants (all reported; only the pre-registered primary is confirmatory)")
    n, hurdle = table["n_trials"].iloc[0], table["sharpe_hurdle"].iloc[0]
    print(f"luck hurdle for the best of {n} variants: Sharpe {hurdle:.2f} (annualized)")
    view = ["method", "doc_types", "hold", "entry", "n_signals", "sharpe", "t_nw", "psr", "dsr", "placebo_p"]
    print(table[[c for c in view if c in table]].round(3).to_string(index=False))


def _sha_files(*paths) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.json")):
                h.update(f.name.encode() + str(f.stat().st_size).encode() + str(int(f.stat().st_mtime)).encode())
        elif p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _fingerprint(stage: str, con, a) -> str | None:
    """Inputs that decide a stage's output. Same fingerprint as last time: the stage is skipped."""
    import datetime
    import hashlib

    from . import evaluate

    src = Path(__file__).parent

    def cfg(*keys) -> str:  # the parts of config/settings.yaml a stage reads
        return hashlib.sha256(
            json.dumps([settings().get(k) for k in keys], sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    scores = hashlib.sha256(
        pd.util.hash_pandas_object(
            db.query(con, "SELECT method, doc_id, score FROM scores ORDER BY method, doc_id"), index=False
        ).values
    ).hexdigest()[:16]
    return {
        "collect": None,  # refreshes the Fed calendar: always run
        "market": str(datetime.date.today()),  # once a day
        "events": _sha_files(
            INTERIM / "documents.csv",
            PROCESSED / "ust_par_yields.csv",
            PROCESSED / "etf_prices.csv",
            src / "align.py",
            src / "policy.py",
        ),
        "baselines": _sha_files(
            INTERIM / "documents.csv",
            src / "dictionary.py",
            src / "supervised.py",
            src / "embeddings.py",
            Path(evaluate.__file__).parent / "validity.py",
            *READERS.values(),
        )
        + str(con.execute("SELECT count(*) FROM label_items").fetchone()[0]),
        "llm-sync": _sha_files(LLM_DIR),
        "audit": _sha_files(LLM_DIR, Path(__file__).parent / "audit.py"),
        "evaluate": scores
        + cfg("splits", "markets")
        + _sha_files(
            PROCESSED / "events.csv",
            PROCESSED / "ust_par_yields.csv",
            Path(evaluate.__file__).parent / "event_study.py",
            src / "policy.py",
        ),
        "backtest": scores
        + str(a.placebo)
        + cfg("backtest", "splits")
        + json.dumps([PRIMARY, DOC_GROUPS])
        + _sha_files(
            PROCESSED / "events.csv", PROCESSED / "etf_prices.csv", Path(evaluate.__file__).parent / "backtest.py"
        ),
        "forecast": scores
        + str(con.execute("SELECT count(*), max(release_date) FROM decisions").fetchone())
        + str(con.execute("SELECT count(*), max(date) FROM yields").fetchone())
        + _sha_files(Path(evaluate.__file__).parent / "forecast.py"),
        "forward": scores
        + cfg("forward", "backtest")
        + json.dumps(PRIMARY)
        + _sha_files(
            PROCESSED / "events.csv",
            PROCESSED / "etf_prices.csv",
            PROCESSED / "ust_par_yields.csv",
            DATA / "forward" / "rules.json",
            Path(evaluate.__file__).parent / "forward.py",
            Path(evaluate.__file__).parent / "backtest.py",
        ),
    }[stage]


FROZEN = ("evaluate", "backtest", "forecast")  # the reported research; after the freeze, the forward test reads on


def cmd_run(a, con):
    """Run stages in order; stages whose inputs are unchanged are skipped (use --force to rerun). After the freeze
    date the research stages stay as reported, whatever new data arrive (use --unfreeze to recompute them)."""
    import time

    order = [
        "collect",
        "market",
        "events",
        "baselines",
        "llm-sync",
        "audit",
        "evaluate",
        "backtest",
        "forecast",
        "forward",
    ]
    stop = order.index(a.until) + 1 if a.until else len(order)
    labels.import_files(con)  # teammates' labels from git
    summary = []
    for name in order[order.index(a.start) : stop]:
        if frozen(a) and name in FROZEN:
            con.execute(
                "INSERT INTO pipeline_runs (stage, status, started_at, finished_at, detail) "
                "VALUES (?, 'skipped', ?, ?, ?)",
                (name, db.now(), db.now(), json.dumps({"reason": f"frozen on {settings()['forward']['freeze']}"})),
            )
            con.commit()
            summary.append((name, "frozen", 0.0))
            print(f"=== {name}: frozen as reported, skipped (fomc run --unfreeze recomputes it) ===")
            continue
        fp = _fingerprint(name, con, a)
        prev = con.execute("SELECT value FROM meta WHERE key = ?", (f"fp:{name}",)).fetchone()
        if fp is not None and prev and prev[0] == fp and not a.force:
            con.execute(
                "INSERT INTO pipeline_runs (stage, status, started_at, finished_at, detail) "
                "VALUES (?, 'skipped', ?, ?, ?)",
                (name, db.now(), db.now(), json.dumps({"reason": "inputs unchanged"})),
            )
            con.commit()
            summary.append((name, "skipped", 0.0))
            print(f"=== {name}: up to date, skipped ===")
            continue
        print(f"\n=== {name} ===")
        t0 = time.monotonic()
        COMMANDS[name](a, con)
        fp = _fingerprint(name, con, a)  # outputs of this stage may feed its own fingerprint
        if fp is not None:
            con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"fp:{name}", fp))
            con.commit()
        summary.append((name, "ran", time.monotonic() - t0))
    from .config import RAW

    tests = Path(__file__).resolve().parents[2] / "tests"
    facts = {
        "raw_files": sum(1 for p in RAW.rglob("*") if p.is_file()) if RAW.exists() else 0,
        "llm_files": sum(1 for _ in LLM_DIR.rglob("*.json")) if LLM_DIR.exists() else 0,
        "tests": sum(f.read_text().count("\ndef test_") for f in tests.glob("test_*.py")) if tests.exists() else 0,
        "tests_by_file": {f.name: f.read_text().count("\ndef test_") for f in sorted(tests.glob("test_*.py"))}
        if tests.exists()
        else {},
    }
    con.execute("INSERT OR REPLACE INTO meta VALUES ('facts', ?)", (json.dumps(facts),))
    con.commit()
    if any(result == "ran" for _, result, _ in summary):
        db.vacuum(con)  # compact after writes: rebuilt FTS pages and replaced rows leave free space
    else:
        db.checkpoint(con)
    print("\nstage        result    seconds")
    for name, result, secs in summary:
        print(f"{name:<12} {result:<9} {secs:7.1f}")


# -------------------------------------------------------------- LLM stages
def cmd_key(a, con):
    from .llm import provider

    if a.action == "set":
        import getpass

        provider.save_key(a.value or getpass.getpass("Anthropic API key (input hidden, paste and press Enter): "))
        print("Saved to .env (git-ignored, mode 600). Checking it with a free Models API call...")
        res = provider.check(a.model)
        print("Key works." if res.get("ok") else f"Check failed: {res.get('error')}")
    elif a.action == "clear":
        provider.clear_key()
        print("Key removed from .env.")
    elif a.action == "check":
        print(json.dumps(provider.check(a.model), indent=1))
    print(json.dumps(provider.status(), indent=1))


def cmd_llm_estimate(a, con):
    from .llm import provider
    from .llm.scorer import Scorer

    cfg = settings()["llm"]
    docs = collect.usable()
    docs = docs[docs.doc_type.isin(a.types)]
    exact = provider.status()["key_configured"] and not a.offline
    ratio, base = {t: WORDS_TO_TOKENS for t in a.types}, 1800
    if exact:
        sc = Scorer(model=a.model)
        sample = _sample(docs, a.per_type * len(a.types), a.types)
        jobs = _jobs("level", sample, a.types)
        probe = type(jobs[0])("level", "probe", jobs[0].system, "x", jobs[0].schema)
        base = sc.count(probe)
        for t in a.types:
            pairs = [(j, w) for j, w, dt in zip(jobs, sample["n_words"], sample["doc_type"]) if dt == t]
            ratio[t] = sum(sc.count(j) - base for j, _ in pairs) / max(1, sum(w for _, w in pairs))
    rows = []
    for t in a.types:
        sub = docs[docs.doc_type == t]
        rows.append(
            {
                "doc_type": t,
                "docs": len(sub),
                "input_tokens": int(len(sub) * base + ratio[t] * sub["n_words"].sum()),
                "output_tokens": len(sub) * cfg["assumed_output_tokens"],
            }
        )
    est = pd.DataFrame(rows)
    for model, p in cfg["prices_per_mtok"].items():
        usd = (est["input_tokens"] * p["input"] + est["output_tokens"] * p["output"]) / 1e6
        est[f"{model} (batch $)"] = (usd * cfg["batch_discount"]).round(2)
    total = est.sum(numeric_only=True)
    total["doc_type"] = "TOTAL"
    est = pd.concat([est, total.to_frame().T], ignore_index=True)
    est[["docs", "input_tokens", "output_tokens"]] = est[["docs", "input_tokens", "output_tokens"]].astype(int)
    print(
        "Exact token counts (free count_tokens endpoint)"
        if exact
        else f"Offline approximation ({WORDS_TO_TOKENS} tokens per word; set a key for exact counts)"
    )
    print(est.to_string(index=False))
    est.to_csv(RESULTS / "llm_cost_estimate.csv", index=False)


def cmd_llm_pilot(a, con):
    from .llm.scorer import Scorer, usage_summary

    sc = Scorer(model=a.model, run_tag=a.run_tag)
    for job in _jobs("level", _sample(collect.usable(), a.n, a.types), a.types):
        rec = sc.call(job)
        ev = (rec.get("checks") or {}).get("evidence", {})
        p = rec.get("parsed") or {}
        print(
            f"{job.key:<34} {rec['status']:<9} stance={p.get('overall_stance')!s:>3} "
            f"score={p.get('stance_score')!s:>5} relevance={p.get('policy_relevance')} "
            f"quotes verified={ev.get('verified')}/{ev.get('n')}"
        )
    print(f"spend so far on {sc.model}: ${usage_summary(sc.model)['cost_usd'].sum():.2f}")
    print(store.sync_llm(con))


def cmd_llm_update(a, con):
    """Score what the corpus gained since the last run, one request at a time: each new document (level) and each
    new decision-to-decision pair (shift). A job with a valid record is never sent again; more than --max new jobs
    means a backfill, which belongs in a Message Batch (fomc llm-submit), so the run stops instead of spending. Once
    this calendar month's direct calls (UTC, list prices) reach llm.monthly_cap_usd it sends nothing more; whatever
    is left waits for the next month."""
    from .llm.scorer import Scorer, month_spend, usage_summary

    sc = Scorer(model=a.model)
    docs = collect.usable()
    todo = [j for j in _jobs("level", docs, TYPES) + _jobs("shift", docs, ["statement"]) if not sc.done(j)]
    if len(todo) > a.max:
        raise SystemExit(f"{len(todo)} new jobs, more than --max {a.max}: submit a Message Batch (fomc llm-submit)")
    cap, spent, sent = float(settings()["llm"]["monthly_cap_usd"]), month_spend(sc.model), 0
    for job in todo:
        if spent >= cap:
            print(f"this month's spend ${spent:.2f} reached the cap of ${cap:.2f}: {len(todo) - sent} jobs wait")
            break
        rec = sc.call(job)
        sent += 1
        spent = month_spend(sc.model)
        print(f"{job.key:<34} {rec['status']}")
    total = usage_summary(sc.model)["cost_usd"].sum()
    print(f"{sent} of {len(todo)} new jobs sent; this month ${spent:.2f} of ${cap:.2f}; all records ${total:.2f}")
    print(store.sync_llm(con))


def cmd_llm_submit(a, con):
    from .llm.scorer import Scorer

    sc = Scorer(model=a.model, run_tag=a.run_tag)
    docs = collect.usable()
    if a.limit:
        docs = _sample(docs, a.limit, a.types)
    batch_id = sc.submit(_jobs(a.what, docs, a.types))
    if batch_id:
        db.upsert(
            con,
            "llm_batches",
            pd.DataFrame(
                [
                    {
                        "batch_id": batch_id,
                        "model": sc.model,
                        "mode": a.what,
                        "n_jobs": None,
                        "status": "submitted",
                        "created_at": db.now(),
                        "collected_at": None,
                    }
                ]
            ),
        )


def cmd_llm_collect(a, con):
    from .llm.scorer import Scorer

    sc = Scorer(model=a.model, run_tag=a.run_tag)
    summary = sc.collect(a.batch_id, _jobs(a.what, collect.usable(), a.types), wait=a.wait)
    print(summary)
    changed = sum(1 for _, why in summary.get("failed", []) if why == "input changed since submission")
    if changed:
        print(f"{changed} results matched no job: collect with the same --what, --types and --run-tag as llm-submit.")
    if summary.get("ok"):  # only a batch that produced records counts as collected
        con.execute(
            "UPDATE llm_batches SET status = 'collected', collected_at = ? WHERE batch_id = ?", (db.now(), a.batch_id)
        )
        con.commit()
        print(store.sync_llm(con))


def cmd_llm_sync(a, con):
    with db.stage(con, "llm-sync") as d:
        d.update(store.sync_llm(con))
    print(d)


def cmd_audit(a, con):
    """Memorization audit; the summary is also stored in the store (meta 'audit') for the dashboard."""
    from . import audit

    with db.stage(con, "audit") as d:
        model = getattr(a, "model", None) or settings()["llm"]["model"]
        ident = audit.identification_report(model)
        inv = audit.invariance_report(model)
        stab = audit.stability_report(model)
        summary = {"model": model}
        drift = audit.drift_report(model)
        if drift:
            summary["drift"] = drift
        if len(ident):
            ident.to_csv(RESULTS / "audit_identification.csv", index=False)
            by = ident.groupby("doc_type")[["exact_month", "same_year", "abs_error_months"]].mean()
            counts = ident["doc_type"].value_counts()
            summary["identify"] = {t: {**row.round(4).to_dict(), "n": int(counts[t])} for t, row in by.iterrows()}
            print(by.round(2))
        if len(inv):
            inv.to_csv(RESULTS / "audit_invariance.csv", index=False)
            summary["invariance"] = inv.round(4).to_dict("records")[0]
            print(inv.round(3).to_string(index=False))
        if len(stab):
            stab.to_csv(RESULTS / "audit_stability.csv", index=False)
            summary["stability"] = stab.round(4).to_dict("records")[0]
            print(stab.round(3).to_string(index=False))
        if len(ident) or len(inv) or len(stab) or drift:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('audit', ?)", (json.dumps(summary, default=float),))
            con.commit()
        else:
            print("No audit records yet: run `fomc llm-submit --what identify` and `--what anon` first.")
        d.update(stored=bool(len(ident) or len(inv) or len(stab)))


def cmd_drift(a, con):
    """This month's re-reading of the eight anchor documents (needs your key; about $0.30 a month). Idempotent: once
    the month's records exist nothing is sent. The comparison itself runs in `fomc audit`."""
    from datetime import UTC, datetime

    from . import audit
    from .llm import scorer

    model = settings()["llm"]["model"]
    ids = audit.anchors(model)
    month = datetime.now(UTC).strftime("%Y-%m")
    sc = scorer.Scorer(model=model, run_tag=audit.drift_tag(month))
    docs = collect.usable()
    todo = [j for j in scorer.level_jobs(docs[docs["doc_id"].isin(ids)]) if not sc.done(j)]
    cap, spent = float(settings()["llm"]["monthly_cap_usd"]), scorer.month_spend(model)
    if todo and spent >= cap:
        print(f"this month's spend ${spent:.2f} reached the cap of ${cap:.2f}: the re-reading waits")
        return
    for job in todo:
        print(f"{job.key:<34} {sc.call(job)['status']}")
    print(f"{month}: {len(ids)} anchors, {len(todo)} read now")
    if todo:
        print(store.sync_llm(con))


# ------------------------------------------------------------- team labels
def cmd_label_sample(a, con):
    added = labels.sample(con, n=a.n, after=a.after, seed=a.seed, batch=a.batch)
    labels.predict(con)
    total = con.execute("SELECT count(*) FROM label_items").fetchone()[0]
    print(f"added {added} sentences ({total} in the set); label them in the dashboard: Research > Label")


def cmd_label_import(a, con):
    r = labels.import_files(con)
    gone = f"; {r['unmatched']} sentences not in this store" if r["unmatched"] else ""
    print(f"{r['labels']} labels from {r['files']} files in data/labels/{gone}")


def cmd_label_report(a, con):
    labels.import_files(con)
    s = labels.summary(con)
    print(f"{s['items']} sentences, {s['labels']} labels, majority label on {s['majority']['n']}")
    for r in s["annotators"]:
        print(f"  {r['annotator']:<16} {r['n']:>4} labeled")
    for r in s["pairs"]:
        print(f"  kappa {r['a']} vs {r['b']}: {r['kappa']:.2f} on {r['n']} sentences (agreement {r['agreement']:.0%})")
    if s["methods"]:
        print(pd.DataFrame(s["methods"]).round(3).to_string(index=False))


def cmd_slides(a, con):
    from . import slides

    for deck in ("main", "technical") if a.deck == "all" else (a.deck,):
        out = slides.build(Path(a.out), base=a.base, deck=deck, pdf_dir=Path(a.pdf).expanduser() if a.pdf else None)
        for kind in ("pdf", "deck", "editable", "outline", "sheet"):
            if kind in out:
                print(f"{kind:<9} {out[kind]}")
        print(f"renders   {out['renders']} (full-size PNGs of every slide and chart)")


# ------------------------------------------------------------------- tools
def cmd_serve(a, con):
    import uvicorn

    if not os.environ.get("FOMC_PUBLIC"):
        labels.import_files(con)  # teammates' labels pulled from git since the last run
    print(f"Dashboard: http://{a.host}:{a.port}")
    uvicorn.run("fomc.api:app", host=a.host, port=a.port, reload=a.reload)


def cmd_status(a, con):
    q = lambda sql: db.query(con, sql)
    print(
        q(
            "SELECT doc_type, count(*) AS docs, min(release_date) AS first, max(release_date) AS last "
            "FROM documents WHERE note IS NULL GROUP BY doc_type"
        ).to_string(index=False)
    )
    print(q("SELECT method, count(*) AS scored FROM scores GROUP BY method").to_string(index=False))
    print(
        q("SELECT stage, status, max(finished_at) AS last_run FROM pipeline_runs GROUP BY stage").to_string(index=False)
    )


def freshness(con, today, cap_reached: bool = False, scoring: bool = True) -> list[tuple[str, bool, str]]:
    """What a scheduled run should have brought in by now: each scheduled decision's statement by the next day and
    its minutes three weeks later, market data within four business days, and a Claude reading of every document
    released three days ago or more (unless this month's cap explains the wait, or there is no key)."""
    import datetime

    def meta(key):
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else []

    day = datetime.timedelta(days=1)
    have = {r[0] for r in con.execute("SELECT doc_id FROM documents WHERE note IS NULL")}
    scheduled = sorted(set(meta("scheduled_meetings")) | set(meta("upcoming_meetings")))
    due = [d for d in scheduled if datetime.date.fromisoformat(d) <= today - day]
    late = [d for d in due if f"statement_{d.replace('-', '')}" not in have]
    due_min = [d for d in scheduled if datetime.date.fromisoformat(d) + 22 * day <= today]
    late_min = [d for d in due_min if f"minutes_{d.replace('-', '')}" not in have]
    checks = [
        ("statements", not late, f"missing for {', '.join(late)}" if late else f"{len(due)} scheduled, all in"),
        ("minutes", not late_min, f"missing for {', '.join(late_min)}" if late_min else f"{len(due_min)} due, all in"),
    ]
    stale = (pd.Timestamp(today) - pd.offsets.BDay(4)).date().isoformat()
    for table in ("yields", "etf_prices"):
        last = con.execute(f"SELECT max(date) FROM {table}").fetchone()[0]  # noqa: S608 (fixed table names)
        checks.append((table, bool(last) and last[:10] >= stale, f"through {last}"))
    if scoring:
        cutoff = (today - 3 * day).isoformat()
        waiting = con.execute(
            "SELECT count(*) FROM documents d WHERE d.note IS NULL AND d.release_date <= ? AND NOT EXISTS "
            "(SELECT 1 FROM scores s WHERE s.doc_id = d.doc_id AND s.method LIKE 'llm:%')",
            (cutoff,),
        ).fetchone()[0]
        why = "; this month's cap explains it" if waiting and cap_reached else ""
        checks.append(("Claude", waiting == 0 or cap_reached, f"{waiting} documents older than 3 days unread{why}"))
    return checks


def cmd_doctor(a, con):
    from .llm import provider

    checks = []
    n = con.execute("SELECT count(*) FROM documents").fetchone()[0]
    checks.append(("database", n > 0, f"{n} documents in {db.DB_PATH.name}"))
    last = con.execute("SELECT max(date) FROM yields").fetchone()[0]
    checks.append(("market data", last is not None, f"yields through {last}"))
    k = con.execute("SELECT count(DISTINCT method) FROM scores").fetchone()[0]
    checks.append(("scores", k > 0, f"{k} scoring methods stored"))
    st = provider.status()
    hint = "configured" if a.strict else st["key_hint"]  # no hint at all in a scheduled run's log
    checks.append(("API key", st["key_configured"], hint if st["key_configured"] else "not set: `fomc key set`"))
    if st["key_configured"] and a.online:
        res = provider.check()
        checks.append(("API check", res["ok"], res.get("display_name") or res.get("error")))
    for name, ok, msg in checks:
        print(f"  [{'ok' if ok else '--'}] {name:<12} {msg}")
    if a.strict:  # for scheduled runs: fail loudly instead of serving a store that quietly stopped growing
        import datetime

        from .llm.scorer import month_spend

        cap = month_spend(settings()["llm"]["model"]) >= float(settings()["llm"]["monthly_cap_usd"])
        fresh = freshness(con, datetime.date.today(), cap_reached=cap, scoring=st["key_configured"])
        for name, ok, msg in fresh:
            print(f"  [{'ok' if ok else '!!'}] {name:<12} {msg}")
        if not all(ok for _, ok, _ in fresh):
            raise SystemExit("something a scheduled run should have brought in is missing (see !! above)")


def cmd_vacuum(a, con):
    before = db.store_bytes()
    db.vacuum(con)
    after = db.store_bytes()
    print(f"store: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


def cmd_export(a, con):
    out = RESULTS / "export"
    out.mkdir(exist_ok=True)
    for table in (
        "documents",
        "events",
        "decisions",
        "scores",
        "validity",
        "event_study",
        "event_curves",
        "backtests",
        "llm_records",
        "label_items",
        "labels",
    ):
        cols = (
            "*"
            if table != "documents"
            else "doc_id, doc_type, meeting_date, release_date, "
            "release_time_et, time_source, url, speaker, speaker_role, title, n_words, note"
        )
        db.query(con, f"SELECT {cols} FROM {table}").to_csv(out / f"{table}.csv", index=False)
    print(f"Exported tables to {out}")


COMMANDS = {
    "collect": cmd_collect,
    "market": cmd_market,
    "events": cmd_events,
    "baselines": cmd_baselines,
    "evaluate": cmd_evaluate,
    "backtest": cmd_backtest,
    "run": cmd_run,
    "key": cmd_key,
    "llm-estimate": cmd_llm_estimate,
    "llm-pilot": cmd_llm_pilot,
    "llm-submit": cmd_llm_submit,
    "llm-update": cmd_llm_update,
    "llm-collect": cmd_llm_collect,
    "llm-sync": cmd_llm_sync,
    "audit": cmd_audit,
    "label-sample": cmd_label_sample,
    "label-import": cmd_label_import,
    "label-report": cmd_label_report,
    "slides": cmd_slides,
    "serve": cmd_serve,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "export": cmd_export,
    "vacuum": cmd_vacuum,
    "roberta": cmd_roberta,
    "finetune": cmd_finetune,
    "forecast": cmd_forecast,
    "forward": cmd_forward,
    "drift": cmd_drift,
}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fomc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    simple = ("collect", "market", "events", "evaluate", "forecast", "forward", "llm-sync")
    for name in (*simple, "status", "export", "vacuum"):
        sub.add_parser(name)
    p = sub.add_parser("baselines")
    p.add_argument("--unfreeze", action="store_true", help="rescore every document and remeasure validity")
    p = sub.add_parser("backtest")
    p.add_argument("--placebo", action="store_true", help="shuffled-score placebo draws (slow)")
    p = sub.add_parser("run", help="run the free pipeline end to end")
    p.add_argument("--start", default="collect")
    p.add_argument("--until")
    p.add_argument("--placebo", action="store_true")
    p.add_argument("--force", action="store_true", help="rerun stages even if their inputs are unchanged")
    p.add_argument("--unfreeze", action="store_true", help="recompute the research stages on data after the freeze")
    p = sub.add_parser("key", help="manage your Anthropic API key")
    p.add_argument("action", choices=["status", "set", "clear", "check"])
    p.add_argument("value", nargs="?")
    p.add_argument("--model")
    p = sub.add_parser("llm-estimate")
    p.add_argument("--model")
    p.add_argument("--types", nargs="+", default=TYPES)
    p.add_argument("--per-type", type=int, default=6)
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("llm-pilot")
    p.add_argument("--model")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--types", nargs="+", default=TYPES)
    p.add_argument("--run-tag", default="")
    for name in ("llm-submit", "llm-collect"):
        p = sub.add_parser(name)
        p.add_argument("--what", choices=["level", "anon", "shift", "identify", "sentences", "team"], default="level")
        p.add_argument("--model")
        p.add_argument("--types", nargs="+", default=TYPES)
        p.add_argument("--run-tag", default="")
        if name == "llm-submit":
            p.add_argument("--limit", type=int, help="evenly spaced sample of this many documents")
        else:
            p.add_argument("--batch-id", required=True)
            p.add_argument("--wait", action="store_true")
    p = sub.add_parser("audit")
    p.add_argument("--model")
    p = sub.add_parser("label-sample", help="sample post-cutoff sentences for the team to label")
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--after", help="first release date (default: start of the post-cutoff split)")
    p.add_argument("--seed", type=int)
    p.add_argument("--batch", default="post_cutoff")
    sub.add_parser("label-import", help="load every teammate's data/labels/*.csv into the store")
    sub.add_parser("roberta", help="FOMC-RoBERTa as an extra yardstick (needs pip install -e .[roberta])")
    sub.add_parser("drift", help="re-score the eight anchor documents for this month (your key; about $0.30)")
    p = sub.add_parser("finetune", help="RoBERTa fine-tuned on the TF-IDF training data (needs .[roberta]; hours)")
    p.add_argument("--team", action="store_true", help="only label the team's sentences with the saved readers")
    p = sub.add_parser("llm-update", help="score only what is new, one request at a time (for scheduled runs)")
    p.add_argument("--model")
    p.add_argument("--max", type=int, default=40, help="stop instead of sending more than this many new jobs")
    sub.add_parser("label-report", help="inter-rater agreement and method accuracy on team labels")
    p = sub.add_parser("slides", help="the integrated Story as PowerPoint (image and editable decks) and an outline")
    p.add_argument("--out", default="docs/slides")
    p.add_argument("--base", help="render from a running dashboard instead of starting one")
    p.add_argument(
        "--deck",
        choices=["main", "technical", "all"],
        default="main",
        help="main: integrated introduction and technical deck (default); technical/all: legacy export options",
    )
    p.add_argument("--pdf", metavar="DIR", help="also write each deck as a PDF in DIR (outside the repository)")
    p = sub.add_parser("serve", help="start the dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p = sub.add_parser("doctor", help="check data, scores and API configuration")
    p.add_argument("--online", action="store_true", help="also verify the key with a free Models API call")
    p.add_argument("--strict", action="store_true", help="fail if anything a scheduled run should bring is missing")
    return ap


def main(argv=None):
    ensure_dirs()
    a = parser().parse_args(argv)
    if not hasattr(a, "placebo"):
        a.placebo = False
    con = _con()
    try:
        COMMANDS[a.cmd](a, con)
    finally:
        db.checkpoint(con)
        con.close()


if __name__ == "__main__":
    sys.exit(main())
