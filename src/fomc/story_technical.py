"""The technical appendix: the same store and slide machinery as the main deck, with the details a reviewer asks about.

`story.build(con, deck="technical")` assembles it from the main deck's context, so every number is read from the
store when the deck is opened and can never disagree with the dashboard. A slide whose data are missing drops out.
Besides the Story's own visuals (steps, tiles, the agenda), three plain ones carry the detail: a table, a block of
code or formulas, and confusion matrices.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import db
from .config import settings
from .llm import rubric

INVENTORY = Path(__file__).with_name("test_inventory.json")

SECTIONS = [
    ("01", "Data and timing", "What is collected, how each release minute is known, and the windows built from it"),
    (
        "02",
        "Measurement",
        "The rubric, the scoring engine, the baselines, a trained transformer and the tests between them",
    ),
    ("03", "Econometrics", "Event study, backtest, next-decision model and forward test, with every control"),
    ("04", "Systems", "Store, pipeline, serving, deployment, operations and tests"),
]
TYPE_NAMES = {"statement": "Statements", "minutes": "Minutes", "presser": "Press conferences", "speech": "Speeches"}
SOURCES = {
    "document_text": "the text",
    "speech_json": "speech feed",
    "default": "standard time",
    "default_no_time": "morning default",
    "calendar": "calendar",
    "convention": "convention",
}
LABELS = ["Dovish", "Hawkish", "Neutral"]  # the Trillion Dollar Words codes 0, 1, 2


def _meta(con, key: str) -> dict:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else {}


def _table(columns, rows, align: str = "", highlight: int | None = None, note: str = "") -> dict:
    """A plain table; `align` has one letter per column, r for right-aligned numbers."""
    return {
        "kind": "table",
        "columns": columns,
        "rows": [[str(x) for x in r] for r in rows],
        "align": align,
        "highlight": highlight,
        "note": note,
    }


def _p(p) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def _label(method: str) -> str:
    from .story import _label as label

    return label(method)


# ------------------------------------------------------------------- frame
def cover(c):
    return {
        "id": "tech-cover",
        "layout": "cover",
        "kicker": f"{c['proj']['group']} · {c['proj']['course']}",
        "title": "How the FOMC Tone Lab is built and tested",
        "subtitle": "The technical appendix: data and timing, measurement, econometrics and systems, with the number "
        "behind each choice",
        "team": c["proj"]["team"],
        "notes": "This is the technical companion to the main deck. Every slide is computed from the same store, so "
        "the "
        "numbers match the dashboard and the main deck. It goes layer by layer: data and timing, measurement, "
        "econometrics, and the systems that keep it running.",
        "link": "#/pipeline",
    }


def agenda(c):
    return {
        "id": "tech-agenda",
        "layout": "wide",
        "kicker": "Roadmap",
        "title": "Four layers, each testable on its own",
        "subtitle": "Data and timing, measurement, econometrics, systems",
        "desk": "Every number here is read from the same store as the main deck and the dashboard, when the deck "
        "opens.",
        "desk_label": "How to read it",
        "source": "Main deck: /story. This appendix: /story?deck=technical. Code: src/fomc/.",
        "notes": "Four layers. Data and timing: what we collect and how we know the minute each document became "
        "public. "
        "Measurement: the rubric, the scoring engine, the baselines, a fine-tuned transformer and the statistics that "
        "compare them. Econometrics: the event study, the backtest, the next-decision model and the forward test. "
        "Systems: the store, the pipeline, serving, deployment and tests.",
        "link": "#/pipeline",
        "visual": {"kind": "agenda", "sections": [list(s) for s in SECTIONS]},
    }


def divider(i):
    num, title, sub = SECTIONS[i]
    return {
        "id": f"tech-part{num}",
        "layout": "divider",
        "kicker": f"Part {num}",
        "number": num,
        "title": title,
        "subtitle": sub,
        "notes": f"Part {num}: {title.lower()}.",
        "link": "#/pipeline",
    }


def closing(c):
    return {
        "id": "tech-closing",
        "layout": "closing",
        "kicker": f"{c['proj']['group']} · {c['proj']['course']}",
        "title": "Thank you",
        "subtitle": "The runbook is docs/OPERATIONS.md; the design is docs/DESIGN.md; every slide links to its page",
        "team": c["proj"]["team"],
        "url": "fedtone.web.app/story?deck=technical",
        "notes": "Thank you. The code, the runbook and the live system are all open to the team; any slide links to "
        "the page behind it.",
        "link": "#/overview",
    }


# ------------------------------------------------------------ data and timing
def corpus(c):
    con = c["con"]
    docs = db.query(
        con,
        "SELECT doc_type, count(*) AS n, sum(n_words) AS w, min(release_date) AS first, max(release_date) AS last "
        "FROM documents WHERE note IS NULL GROUP BY doc_type",
    ).set_index("doc_type")
    if docs.empty:
        return None
    src = db.query(con, "SELECT doc_type, time_source, count(*) AS n FROM documents WHERE note IS NULL GROUP BY 1, 2")
    out = dict(con.execute("SELECT doc_type, count(*) FROM documents WHERE note IS NOT NULL GROUP BY 1").fetchall())
    rows = []
    for t in TYPE_NAMES:
        if t not in docs.index:
            continue
        r = docs.loc[t]
        s = src[src["doc_type"] == t].sort_values("n", ascending=False)
        rows.append(
            [
                TYPE_NAMES[t],
                f"{int(r['n']):,}",
                f"{r['w'] / 1e6:.2f}M",
                r["first"],
                r["last"],
                ", ".join(f"{SOURCES.get(x.time_source, x.time_source)} {x.n:,}" for x in s.itertuples()),
                f"{out.get(t, 0):,}",
            ]
        )
    total, words = int(docs["n"].sum()), float(docs["w"].sum())
    return {
        "id": "tech-corpus",
        "layout": "wide",
        "kicker": "Corpus",
        "title": f"{total:,} documents, each with its minute",
        "subtitle": "When each became public, and where that minute comes from",
        "desk": "The release minute decides which prices a document could have moved, so its source is kept with it.",
        "desk_label": "Why it matters",
        "source": "Federal Reserve Board: FOMC calendar, statements, minutes, press-conference transcripts, speech "
        "feed; "
        "pages cached by URL.",
        "notes": f"{total:,} documents and {words / 1e6:.1f} million words after cleaning. Press conferences keep the "
        "Chair's words only: reporters' questions and the moderator are removed. Minutes drop the attendance list. "
        "Speeches shorter than 300 words are left out, which is most of the excluded count. The last column shows "
        "where each release minute comes from: the statement's own text, the Fed's speech feed, or the standard time.",
        "link": "#/documents",
        "visual": _table(
            ["Type", "Documents", "Words", "First", "Last", "Release minute from", "Excluded"],
            rows,
            align="lrrllll",
        ),
    }


def windows(c):
    ev = db.query(c["con"], "SELECT doc_type, ust_window_days AS d, count(*) AS n FROM events GROUP BY 1, 2")
    if ev.empty:
        return None
    two = int(ev.loc[ev["d"] == 2, "n"].sum())
    gap = settings()["markets"]["ambiguous_minutes"]
    return {
        "id": "tech-windows",
        "kicker": "No look-ahead",
        "title": "Windows start at the release minute",
        "subtitle": "And close at the first price the release could move",
        "number": f"{int(ev['n'].sum()):,}",
        "number_label": f"release windows; {two:,} span two Treasury fixes",
        "chips": [
            f"{TYPE_NAMES[t]}: {int(g['n'].sum()):,}"
            + (f", {int(g.loc[g['d'] == 2, 'n'].sum())} over two fixes" if (g["d"] == 2).any() else "")
            for t, g in ev.groupby("doc_type")
            if t in TYPE_NAMES
        ],
        "desk": "No price fixed before a release can enter its window or its trade; tests in tests/test_timing.py hold "
        "each rule.",
        "source": "src/fomc/align.py; Treasury par yields fixed near 3:30 p.m. ET; ETF closes at 4:00 p.m. ET.",
        "notes": "The window for a 2 p.m. statement runs from the 3:30 fix the day before to the 3:30 fix the same "
        "day. "
        "A press conference starts at 2:30 and runs past the fix, so it gets two days. Speech times come from the "
        f"Fed's feed; a speech within {gap} minutes of a close counts as after it. Trades enter at a 4 p.m. ETF close "
        "and earn from the next day, so a position never uses the price it was set at.",
        "link": "#/documents",
        "visual": {
            "kind": "steps",
            "steps": [
                ["Release minute", "from the statement's text, the speech feed, or the standard 2:00 p.m."],
                ["Before", "the last 3:30 p.m. Treasury fix before that minute"],
                ["After", "the first fix after it: two days when a press conference straddles the fix"],
                ["Near a close", f"a speech within {gap} minutes of a 4:00 p.m. close counts as after it"],
                ["Entry", "the next 4:00 p.m. ETF close, or the one after (the pre-registered trade)"],
                ["Earning", "from the following day; weekends and holidays roll to the next trading day"],
            ],
        },
    }


# ---------------------------------------------------------------- measurement
def rubric_slide(c):
    dims = rubric.DIMENSIONS
    pad = max(len(d) for d in dims) + 4
    lines = ["{", '  "policy_relevance": "high | medium | low",']
    lines += [f'  "{d}":'.ljust(pad + 5) + "-2 … +2 | null," for d in dims]
    lines += [
        '  "overall_stance":'.ljust(pad + 5) + "-2 … +2,      # holistic, not an average",
        '  "stance_score":'.ljust(pad + 5) + "-1.0 … +1.0,  # the index",
        '  "confidence":'.ljust(pad + 5) + "0 … 1,",
        '  "evidence": [{"dimension": …, "quote": "verbatim"}]',
        "}",
    ]
    return {
        "id": "tech-rubric",
        "kicker": f"Rubric {rubric.RUBRIC_VERSION}",
        "title": "One rubric, enforced as a JSON schema",
        "subtitle": "Positive is hawkish; negative is dovish; stance_score is the index",
        "number": str(len(dims)),
        "number_label": "policy dimensions, each from −2 to +2, then an overall stance and a continuous score",
        "chips": [
            "Structured outputs: the schema is the contract, no free text to parse",
            "The scorer sees the document type and the text, never the date",
            f"Any change to the prompt or schema bumps {rubric.RUBRIC_VERSION} and starts new records",
        ],
        "desk": "The stance_score is the index; dimensions explain it and quotes locate supporting language.",
        "source": "src/fomc/llm/rubric.py (prompts and schemas); src/fomc/llm/scorer.py (jobs, records, checks).",
        "notes": "Each level reading returns this object. Six dimensions on an integer scale from minus two to plus "
        "two, "
        "null when a document does not address one; an overall stance that weighs forward guidance and the balance of "
        "risks most; a continuous score for finer ranking between documents with the same stance; a confidence; and "
        "evidence quotes tied to a dimension. The schema is enforced by structured outputs, so nothing is parsed from "
        "prose.",
        "link": "#/live",
        "visual": {"kind": "code", "lines": lines},
    }


def engine(c):
    con = c["con"]
    u = con.execute(
        "SELECT count(*), sum(input_tokens), sum(output_tokens), sum(cache_read_tokens), sum(cost_usd), "
        "count(DISTINCT batch_id), sum(batch_id IS NULL), sum(status != 'ok') FROM llm_records"
    ).fetchone()
    if not u or not u[0]:
        return None
    n, inp, out, cache, cost, batches, direct, failed = u
    as_of = con.execute("SELECT max(created_at) FROM llm_records").fetchone()[0]
    as_of = str(as_of or "unknown")[:10]
    cfg = settings()["llm"]
    rows = [
        ["Model", f"{cfg['model']}, adaptive thinking, effort {cfg['effort']}"],
        ["Output", "structured JSON against the rubric's schema; quotes located in the source"],
        ["Batching", f"{batches} Message Batches at half price; {direct} direct calls"],
        ["Prompt cache", f"{(cache or 0) / 1e6:.1f}M input tokens read from the cache"],
        ["Tokens", f"{(inp or 0) / 1e6:.1f}M in, {(out or 0) / 1e6:.2f}M out"],
        ["Records", f"{n:,}, each keyed by a hash of prompt, schema and text"],
        ["Failures", f"{failed or 0} failed requests"],
        ["Caps", f"at most 40 new jobs a run; {cfg['monthly_cap_usd']:.0f} USD a month of scheduled scoring"],
    ]
    return {
        "id": "tech-engine",
        "kicker": "Scoring engine",
        "title": "Cached requests and auditable spending",
        "subtitle": f"Operational snapshot through {as_of}, including monthly re-reads",
        "number": f"${cost:.2f}",
        "number_label": f"for {n:,} stored Claude records; operations continue after the research freeze",
        "chips": [
            "A record's key changes with the prompt, schema or text, never otherwise",
            "Records live in git: a rebuilt store costs nothing",
            "Refusals, truncation and schema misses are recorded, not retried silently",
        ],
        "desk": "Every reading is reproducible from its record: request and message IDs, tokens, cost and raw text.",
        "source": "src/fomc/llm/provider.py (credentials), scorer.py (jobs, batches, records); data/llm/ in git.",
        "notes": f"All Claude traffic goes through one module. The full corpus ran as {batches} Message Batches at "
        "half "
        f"price, with the system prompt cached. Each record is keyed by a hash of prompt, schema and text, so a rerun "
        f"never pays twice, and the {n:,} records are committed. {direct} direct calls are the scheduled scoring of "
        f"new "
        "documents and the monthly re-read.",
        "link": "#/pipeline",
        "visual": _table(["Piece", "Setting"], rows, align="ll"),
    }


def evidence(c):
    r = (
        c["con"]
        .execute(
            "SELECT count(*), avg(evidence_share), min(evidence_share), sum(evidence_share = 1) FROM llm_records "
            "WHERE mode = 'level' AND coalesce(run_tag, '') = '' AND status = 'ok'"
        )
        .fetchone()
    )
    if not r or not r[0]:
        return None
    n, share, low, full = r
    return {
        "id": "tech-evidence",
        "kicker": "Evidence check",
        "title": f"{share:.2%} mean evidence-match share",
        "subtitle": "Every quote Claude cites is looked up in the cleaned source text",
        "number": f"{share:.2%}",
        "number_label": f"mean document-level quote-match share over {n:,} documents",
        "chips": [
            "Matching ignores typography: quotes, dashes and spaces",
            "Each quote is stored with its character span",
            "The share is kept per document and shown beside its score",
        ],
        "desk": "A score whose evidence is not in the document is a flag to read, not a number to average.",
        "source": "src/fomc/llm/scorer.py (verify); Documents shows each score with its quotes highlighted.",
        "notes": f"After each answer, every quote is searched in the cleaned text, ignoring curly quotes, dash "
        "types and "
        f"spacing. {full:,} of {n:,} documents have every quote found; the lowest share in any document is "
        f"{low:.0%}. The share is stored with the score, and the Documents page highlights each quote in place.",
        "link": "#/documents",
        "visual": {
            "kind": "tiles",
            "tiles": [
                [f"{n - full:,}", "documents with an unmatched evidence quote"],
                [f"{full:,}", f"of {n:,} documents with every quote found"],
                [f"{low:.0%}", "the lowest share in any one document"],
                [f"{n:,}", "documents with a stored evidence share"],
            ],
        },
    }


def baselines(c):
    val = c["val"].set_index("method") if len(c["val"]) else None
    if val is None:
        return None
    cv = _meta(c["con"], "baseline_cv")
    readers = _meta(c["con"], "readers").get("roberta_tuned", {})
    llm = next((m for m in val.index if m.startswith("llm:")), None)

    def f1(m):
        return f"{val.loc[m, 'macro_f1']:.3f}" if m in val.index else "–"

    def cvf(m):
        return f"{cv[m]['cv_macro_f1']:.3f}" if m in cv else "–"

    rows = [
        ["Dictionary", "policy nouns near direction words", "signed rules", "none", "–", f1("dictionary")],
        [
            "TF-IDF",
            "unigrams and bigrams, min_df 2, sublinear tf",
            "logistic regression, balanced",
            f"C = {cv.get('supervised', {}).get('best_C', '–')} of 0.5 to 8",
            cvf("supervised"),
            f1("supervised"),
        ],
        [
            "Sentence embeddings",
            "all-MiniLM-L6-v2, 384 dimensions, ONNX",
            "logistic regression, balanced",
            f"C = {cv.get('embedding', {}).get('best_C', '–')} of 0.25 to 16",
            cvf("embedding"),
            f1("embedding"),
        ],
    ]
    if readers.get("chosen"):
        rows.append(
            [
                "Fine-tuned RoBERTa",
                "RoBERTa-large, 355M parameters",
                "fine-tuned end to end",
                f"{len(readers['search'])} settings × 5 folds",
                f"{readers['chosen']['cv_macro_f1']:.3f}",
                f1("roberta_tuned"),
            ]
        )
    if llm:
        rows.append(["Claude Opus 5.5", "sentences (H1); documents (index)", "zero-shot rubric", "none", "–", f1(llm)])
    return {
        "id": "tech-baselines",
        "layout": "wide",
        "kicker": "Readers",
        "title": "Same 1,984 sentences, same five folds",
        "subtitle": "H1 uses the same test sentences; corpus scoring uses full documents",
        "desk": "Same data, same folds, same score: the readers differ only in how they represent a sentence.",
        "desk_label": "Why it matters",
        "source": "Trillion Dollar Words (Shah, Paturi and Chava, ACL 2023), train split 1,984, test split 496; "
        "dictionary.py, supervised.py, embeddings.py, finetune.py.",
        "notes": "Five readers. The dictionary needs no training. TF-IDF and sentence embeddings each fit a balanced "
        "logistic regression, with the penalty chosen by five-fold cross-validated macro-F1 on the train split. The "
        "RoBERTa reference uses the same folds and score. Claude reads the same test sentences for H1, and whole "
        "documents for the index, without task-specific training. A "
        "document's score for the sentence readers is the mean of P(hawkish) minus P(dovish) over its sentences.",
        "link": "#/validity",
        "visual": _table(
            ["Reader", "Representation", "Classifier", "Tuned", "CV macro-F1", "Test macro-F1"],
            rows,
            align="llllrr",
            note="Trained sentence-reader index: mean[P(hawkish) − P(dovish)]; Claude uses a holistic document rubric.",
        ),
    }


def search(c):
    r = _meta(c["con"], "readers").get("roberta_tuned", {})
    if not r.get("search"):
        return None
    chosen = r["chosen"]

    def key(cfg):
        return json.dumps(cfg, sort_keys=True)

    points = []
    for entry in r["search"]:
        cfg = entry["config"]
        size = cfg["backbone"].split("-")[-1]
        lr = f"{cfg['lr']:.0e}".replace("e-0", "e-")
        extras = ("; decay 0.9" if cfg["llrd"] != 1 else "") + (f"; b{cfg['batch']}" if cfg["batch"] != 16 else "")
        mean, sd = entry["cv_macro_f1"], entry["fold_sd"]
        points.append(
            {
                "label": f"{size}; {lr}{extras}",
                "value": mean,
                "low": mean - sd,
                "high": mean + sd,
                "highlight": key(cfg) == key(chosen["config"]),
                "details": f"best epoch {entry['best_epoch']}; batch {cfg['batch']}; fold SD {sd:.3f}",
            }
        )
    cfg = chosen["config"]
    return {
        "id": "tech-search",
        "kicker": "Fine-tuning RoBERTa",
        "title": "Nine settings, five folds, five seeds",
        "subtitle": "The best setting is refit on all 1,984 sentences with five seeds, then averaged",
        "number": f"{chosen['cv_macro_f1']:.3f}",
        "number_label": f"cross-validated macro-F1 of RoBERTa-{cfg['backbone'].split('-')[-1]} at "
        f"{cfg['lr']:.0e}".replace("e-0", "e-")
        + f", epoch {chosen['epoch']} of ten",
        "chips": [
            "AdamW, betas 0.9 and 0.98, eps 1e-6, weight decay 0.01",
            "10% warmup, linear decay; class-balanced loss; gradients clipped at 1",
            "Validation macro-F1 after every epoch: the epoch is chosen too",
        ],
        "desk": "The test split was read once, by the chosen setting; every setting tried is in the record.",
        "source": "src/fomc/finetune.py; data/baselines/roberta-tuned.json (search, revisions, labels, scores).",
        "notes": "The search ran RoBERTa-base at four learning rates and RoBERTa-large at three, then two "
        "refinements of "
        "the best: layer-wise learning-rate decay and batches of 32. Each setting ran on the TF-IDF baseline's five "
        "folds for ten epochs, scored after each, so the epoch with the best average was chosen with the rest. The "
        "winner was refit on all 1,984 sentences with five seeds, stopped at that epoch, and their probabilities "
        "averaged.",
        "link": "#/validity",
        "visual": {
            "kind": "intervals",
            "axis": "Cross-validated macro-F1",
            "digits": 3,
            "interval": "Mean ±1 fold SD; purple is the chosen setting",
            "zero": False,
            "rows": points,
        },
    }


def mps(c):
    if not _meta(c["con"], "readers").get("roberta_tuned"):
        return None
    rows = [
        ["Gradient clipping", "182 ms", "7 ms", "one flat gradient buffer, norm by a dot product"],
        ["Optimizer step", "42 ms", "26 ms", "fused AdamW"],
        ["Forward and backward", "101 ms", "101 ms", "the model's own cost, unchanged"],
        ["RoBERTa-base, one fold", "5.6 min", "2.3 min", "ten epochs on 1,587 sentences"],
        ["RoBERTa-large, batch 32", "5.4 h", "5.4 min", "two passes of 16 add up (memory)"],
        ["Mixed precision", "–", "not used", "bf16 was slower on this GPU"],
    ]
    return {
        "id": "tech-mps",
        "kicker": "Training on a laptop GPU",
        "title": "The bottleneck was clipping, not the model",
        "subtitle": "On the laptop's GPU, one library call took longer than the network itself",
        "number": "2.4×",
        "number_label": "faster training steps on an M4 Pro, with the same arithmetic",
        "chips": [
            "torch.linalg.vector_norm over 125M values: 102 ms on MPS; a dot product: 2 ms",
            "Every gradient is a view of one buffer, so clipping is two operations",
            "Length-grouped batches cut padding; the search resumes run by run",
        ],
        "desk": "Measure before optimizing: the slow step was a library call, and the fix changed no result.",
        "source": "Benchmarks on an Apple M4 Pro GPU (MPS), PyTorch 2.14, RoBERTa-base, batches of 16; finetune.py.",
        "notes": "Profiling one training step showed clipping took 182 milliseconds, more than forward and backward "
        "together, because the built-in norm is slow on Apple's GPU backend. Putting every gradient in one buffer and "
        "taking the norm as a dot product made it 7 milliseconds, with the same clipping. RoBERTa-large at batches "
        "of 32 "
        "filled the 24 gigabytes and swapped, so larger batches add up two passes of 16, which gives the same update.",
        "link": "#/validity",
        "visual": _table(["Step", "Before", "After", "How"], rows, align="lrrl"),
    }


def validity_tests(c):
    val = c["val"]
    if not len(val):
        return None
    tests = {t["method"]: t for t in (_meta(c["con"], "validity_tests") or [])}
    llm = next((m for m in val["method"] if m.startswith("llm:")), None)
    if not llm:
        return None
    rows = []
    for r in val.itertuples():
        t = tests.get(r.method)
        rows.append(
            [
                _label(r.method),
                f"{r.accuracy:.3f}",
                f"{r.macro_f1:.3f}",
                f"{r.cohen_kappa:.3f}",
                f"{t['f1_diff']:+.3f}" if t else "–",
                f"{t['ci_low']:+.3f} to {t['ci_high']:+.3f}" if t else "–",
                _p(t["p_boot"]) if t else "–",
                _p(t["mcnemar_p"]) if t else "–",
            ]
        )
    f1 = float(val.loc[val["method"] == llm, "macro_f1"].iloc[0])
    behind = [m for m, t in tests.items() if t["f1_diff"] < 0 and t["p_boot"] < 0.05]
    title = "Ahead of the baselines, behind a trained model" if behind else "Ahead of every baseline"
    return {
        "id": "tech-validity",
        "layout": "wide",
        "kicker": "Validity statistics",
        "title": title,
        "subtitle": "Paired macro-F1 gaps on public expert labels; positive favors Claude",
        "desk": "A paired test on the same sentences: each reader's gap to Claude, its interval, and the sentences "
        "only "
        "one of them gets right.",
        "desk_label": "How to read it",
        "source": f"{int(val['n'].iloc[0])} Trillion Dollar Words test sentences; paired bootstrap of the macro-F1 gap "
        "(2,000 resamples); McNemar's exact test; evaluate/validity.py.",
        "notes": f"Claude's macro-F1 is {f1:.3f}. Against each reader, the gap is bootstrapped by resampling the same "
        "sentences 2,000 times; the interval and two-sided p come from that distribution. McNemar's test uses only the "
        "sentences the two readers label differently. These labels have been public since 2023 and may be in training. "
        "The post-cutoff human test was not run; masked/raw agreement partly addresses contamination risk.",
        "link": "#/validity",
        "visual": _table(
            ["Reader", "Accuracy", "Macro-F1", "Kappa", "Claude − reader F1", "95% interval", "p", "McNemar p"],
            rows,
            align="lrrrrrrr",
            highlight=next((i for i, r in enumerate(val.itertuples()) if r.method == llm), None),
        ),
    }


def confusions(c):
    conf = _meta(c["con"], "validity_confusions")
    llm = next((m for m in conf if m.startswith("llm:")), None)
    if not llm:
        return None
    m = conf[llm]
    misses = [(m[i][j], i, j) for i in range(3) for j in range(3) if i != j]
    n, i, j = max(misses)
    items = [{"title": _label(llm), "m": m}]
    for other in ("roberta_tuned", "supervised"):
        if other in conf:
            items.append({"title": _label(other), "m": conf[other]})

    def recall(mat, k):
        return mat[k][k] / sum(mat[k]) if sum(mat[k]) else 0

    chips = [f"{LABELS[k]} recall: Claude {recall(m, k):.0%}" for k in range(3)]
    if "roberta_tuned" in conf:
        chips = [f"{c_} · RoBERTa {recall(conf['roberta_tuned'], k):.0%}" for k, c_ in enumerate(chips)]
    return {
        "id": "tech-confusions",
        "kicker": "Where the readers miss",
        "title": f"Commonest miss: {LABELS[i].lower()} read as {LABELS[j].lower()}",
        "subtitle": "Each reader's labels against the experts' on the 496 test sentences",
        "number": f"{n}",
        "number_label": f"of {sum(m[i])} {LABELS[i].lower()} test sentences Claude read as {LABELS[j].lower()}",
        "chips": chips,
        "desk": "Shading is each row's share: a dark diagonal is a reader that agrees with the experts.",
        "source": "Rows: the experts' label; columns: the reader's; Trillion Dollar Words test split.",
        "notes": f"The matrices count the 496 test sentences by the experts' label in rows and the reader's label in "
        f"columns. Claude's largest error is reading {LABELS[i].lower()} sentences as {LABELS[j].lower()}: it leans "
        "where the annotators saw none, which fits a reader of whole documents applied to single sentences.",
        "link": "#/validity",
        "visual": {"kind": "matrices", "labels": LABELS, "items": items},
    }


def reliability(c):
    a = c["audit"]
    st, idf, inv, dr = a.get("stability"), a.get("identify"), a.get("invariance"), a.get("drift")
    if not st:
        return None
    idf = (idf or {}).get("statement")
    last = (dr or {}).get("months", [])[-1:] or [None]
    last = last[0]
    tiles = [
        [
            f"{st['within_one_step']:.0%}",
            f"{st['n']} repeated documents: stance within one step on the five-point scale",
        ]
    ]
    if idf:
        tiles.append(
            [f"{idf['exact_month']:.0%}", f"of {idf.get('n', 'sampled')} masked statements dated to the exact month"]
        )
    if inv:
        tiles.append([f"r = {inv['corr_stance_score']:.2f}", f"masked against raw scores on {inv['n']} documents"])
    if last:
        tiles.append(
            [
                f"{last['overall_stance_agreement']:.0%}",
                f"same stance on the {last['n']} anchors re-read in {last['month']}; mean change "
                f"{last['mean_abs_diff']:.3f}",
            ]
        )
    return {
        "id": "tech-reliability",
        "kicker": "Reliability and memorization",
        "title": "Stable scores under masking and re-reading",
        "subtitle": "Masking dates and names barely moves scores; it cannot rule out contamination",
        "number": f"{st['corr_stance_score']:.3f}",
        "number_label": f"correlation between two separate batches on {st['n']} documents",
        "chips": [
            f"Same stance on {st['overall_stance_agreement']:.1%} of {st['n']} repeated documents",
            f"Mean change {st['mean_abs_diff']:.3f} on a scale of −1 to +1",
            "Drift flag: mean change above 0.10 or stance agreement below 75%",
        ],
        "desk": "Masking dates and names barely changes scores; recognition risk and possible shared bias remain.",
        "source": "audit.py: stability (run tag r2), identification and invariance (masked), drift (monthly anchors).",
        "notes": "Four checks. A separate batch of 152 documents re-scored gives r of 0.996. Masked statements are "
        "dated to the exact month almost every time, consistent with recognition but not proof of memorization. "
        "Scores with dates, names and rate "
        "levels masked track the raw ones at r of 0.99. Every month eight anchor documents are read again through "
        "the current model and pipeline; a change past the limits starts a new experiment.",
        "link": "#/validity",
        "visual": {"kind": "tiles", "tiles": tiles},
    }


# --------------------------------------------------------------- econometrics
def event_spec(c):
    es = c["es"]
    if not len(es):
        return None
    tests, surv = c["tests"], c["survivors"]
    k_llm = int(surv["method"].str.startswith("llm").sum())
    lines = [
        "Δy = α + β · tone_z + γ' · controls + ε          # OLS, HC1 errors",
        "",
        "tone_z    a reader's score (level) or its change since the",
        "          previous document of the type (shift), standardized",
        "groups    statements, minutes, press conferences, speeches",
        "          (and the Chair's against other members')",
        "y         3m, 2y, 5y, 10y, 30y and 2s10s over the window;",
        "          the day before (placebo); 5 and 20 days after (drift)",
        "controls  3-month bill (the surprise), the announced move,",
        "          TF-IDF tone of the same document; split samples",
        f"family    Benjamini-Hochberg q over the {len(tests)} main tests",
    ]
    return {
        "id": "tech-event",
        "kicker": "Event study",
        "title": f"{len(es):,} regressions, one FDR family",
        "subtitle": "Exploratory main-grid tests share one BH adjustment; diagnostics are separate",
        "number": f"{len(surv)} / {len(tests)}",
        "number_label": f"main tests survive q < 0.10, {k_llm} of them on Claude's reading",
        "chips": [
            "β in basis points per standard deviation of tone",
            "Statements are compared decision with decision",
            "Controls and split samples are exploratory diagnostics outside the main family",
        ],
        "desk": "BH adjustment addresses the main-grid search; it does not identify an exogenous communication shock.",
        "source": "Stored OLS, HC1 errors; observational associations. Only the H3 primary trade was pre-registered.",
        "notes": f"One specification across the grid: the yield change over the release window on standardized tone, "
        f"with HC1 errors. The main grid crosses four document groups, the readers, level and shift, and six "
        f"outcomes: {len(tests)} tests, with Benjamini-Hochberg q-values across all of them. {len(surv)} survive at q "
        "below 0.10. Controls, split samples, the day-before placebo and the drift outcomes are reported beside each "
        "test, outside the family.",
        "link": "#/event-study",
        "visual": {"kind": "code", "lines": lines},
    }


def robustness(c):
    es, best = c["es"], c["best"]
    if best is None or not len(es):
        return None
    sel = es[
        (es["doc_type"] == best["doc_type"]) & (es["method"] == best["method"]) & (es["regressor"] == best["regressor"])
    ]

    def point(name, outcome, sample="all", control="none", note=""):
        found = sel[(sel["outcome"] == outcome) & (sel["sample"] == sample) & (sel["control"] == control)]
        if not len(found):
            return None
        r = found.iloc[0]
        beta, t = float(r["beta_bp_per_sd"]), float(r["t"])
        se = abs(beta / t) if t else 0.0
        return {
            "label": name,
            "value": beta,
            "low": beta - 1.96 * se,
            "high": beta + 1.96 * se,
            "n": int(r["n"]),
            "t": t,
            "highlight": name == "Headline",
            "details": f"n = {int(r['n'])}; t = {t:.2f}" + (f"; {note}" if note else ""),
        }

    points = [
        point("Headline", "d2y", note=f"q = {best['q_bh']:.3f}" if pd.notna(best["q_bh"]) else ""),
        point("3-month bill control", "d2y", control="d3m", note="near-term surprise"),
        point("Announced move control", "d2y", control="decision"),
        point("TF-IDF tone control", "d2y", control="baseline", note="word-count tone"),
        point("2009 to 2019", "d2y", sample="development"),
        point("Jan 2020 to Jun 2026", "d2y", sample="holdout"),
        point("Day-before placebo", "pre_d2y"),
        point("5-day drift", "drift5_d2y"),
        point("20-day drift", "drift20_d2y"),
    ]
    points = [p for p in points if p]
    group = {"statement": "statement", "minutes": "minutes", "presser": "press-conference", "speech": "speech"}.get(
        best["doc_type"], best["doc_type"]
    )
    held = all(p["t"] >= 2 for p in points[1:6])
    return {
        "id": "tech-robustness",
        "kicker": "The headline, stress-tested",
        "title": f"The {group} association " + ("across checks" if held else "under stress"),
        "subtitle": "The association survives controls and sample splits; no significant later drift",
        "number": f"t = {best['t']:.2f}",
        "number_label": f"{best['beta_bp_per_sd']:+.2f} bp on the 2-year per standard deviation of "
        f"{_label(best['method'])}'s {best['regressor']}",
        "chips": [f"{p['label']}: t = {p['t']:.2f}" for p in points[1:4]],
        "desk": "Control and split-sample checks do not separate an exogenous language shock from shared news.",
        "source": "Stored event-study estimates; 95% intervals use β ± 1.96 HC1 SE from unrounded β/t; no refitting.",
        "notes": "The strongest 2-year relationship, read across every robustness row. The near-term surprise, the "
        "announced move and the TF-IDF tone of the same transcript each leave it significant, so Claude reads "
        "something the decision and word counts do not. It holds in both halves of the sample. The day-before "
        "placebo is weaker and later drift is not statistically detectable; full market pricing is not established.",
        "link": "#/event-study",
        "visual": {
            "kind": "intervals",
            "axis": "2-year move, bp per SD of tone",
            "digits": 2,
            "interval": "95% HC1 intervals; hollow dots cross zero",
            "zero": True,
            "rows": points,
        },
    }


def backtest_math(c):
    p = c["primary"]
    if p is None:
        return None
    cfg = settings()["backtest"]
    d = cfg["durations"]
    k = cfg["duration_budget_years"] / (d[cfg["long_etf"]] - d[cfg["short_etf"]])
    lines = [
        f"z_i  = (s_i − mean_earlier) / sd_earlier    # same type, ≥ {cfg['zscore_min_events']} earlier",
        "θ_i  = −clip(z_i, −2, 2) / 2              # hawkish → shorter",
        f"pos_t = clip(Σ θ_i over open trades, −1, 1)  # each held {cfg['holding_days'][0]} days",
        f"r_t  = pos_(t−1) · (r_{cfg['long_etf']} − r_{cfg['short_etf']})"
        f" − 2 × {cfg['cost_bp_per_side']:g} bp × |Δpos_t|",
        f"tilt = {k:.3f} of the portfolio per unit    # ± {cfg['duration_budget_years']:g} year of duration",
        "",
        "PSR (probabilistic Sharpe) =",
        "  Φ((SR − 0) · √(T−1) / √(1 − γ3·SR + (γ4−1)/4 · SR²))",
        "DSR (deflated Sharpe): benchmark = E[max SR of N no-skill variants]",
        "SR: daily Sharpe; T: days; γ3: skewness; γ4: kurtosis; Φ: normal CDF",
    ]
    return {
        "id": "tech-backtest",
        "kicker": "The pre-registered trade",
        "title": "A trade fixed in advance",
        "subtitle": "Standardize, cap, hold five days, pay costs: the code is the pre-registration",
        "number": f"{p['sharpe']:+.2f}",
        "number_label": "Sharpe of the pre-registered tilt: Claude on minutes and speeches, next-day entry",
        "chips": [
            f"Newey-West t = {p['t_nw']:.2f}; hit rate {p['hit_rate']:.0%}",
            f"Shuffled-score placebo p = {p['placebo_p']:.2f} ({cfg['placebo_draws']} draws)",
            f"Probabilistic Sharpe {p['psr']:.0%}; {p['active_bp']:+.0f} bp a year on AGG",
        ],
        "desk": "Every parameter was written down before the first run; the code is the pre-registration.",
        "source": f"evaluate/backtest.py; {cfg['long_etf']} minus {cfg['short_etf']}, durations held at "
        f"{d[cfg['long_etf']]} and {d[cfg['short_etf']]} years; Bailey and López de Prado (2012, 2014).",
        "notes": "Signals are standardized against earlier documents of the same type only. A hawkish document sets a "
        "negative position, capped so one signal moves at most half a unit and all open trades at most one. Returns "
        "are the IEF-minus-SHY spread with costs on both legs for every change. The probabilistic Sharpe ratio allows "
        "for skew and fat tails; the deflated one raises the bar to what the best of all variants would show by luck.",
        "link": "#/backtest",
        "visual": {"kind": "code", "lines": lines},
    }


def selection(c):
    bt, p = c["bt"], c["primary"]
    if not len(bt) or p is None:
        return None
    above = int((bt["dsr"] > 0.95).sum()) if "dsr" in bt else 0
    rows = [
        ["Variants run", f"{len(bt)}", "every one reported and counted"],
        ["Best Sharpe among them", f"{bt['sharpe'].max():.2f}", f"{_label(bt.loc[bt['sharpe'].idxmax(), 'method'])}"],
        ["Luck hurdle", f"{p['sharpe_hurdle']:.2f}", f"expected best Sharpe of {int(p['n_trials'])} no-skill variants"],
        ["Primary Sharpe", f"{p['sharpe']:.2f}", "the one test written down first"],
        ["Primary probabilistic Sharpe", f"{p['psr']:.0%}", "confidence its true Sharpe is above zero"],
        ["Primary placebo p", f"{p['placebo_p']:.2f}", "share of shuffled-score Sharpes at least as high"],
        ["Variants past the hurdle", f"{above}", "deflated Sharpe above 95%"],
    ]
    return {
        "id": "tech-selection",
        "kicker": "Selection bias",
        "title": f"{len(bt)} variants, none past the luck hurdle",
        "subtitle": "All counted: none clears what luck alone would give the best of them",
        "number": f"{above}",
        "number_label": f"of {len(bt)} variants above the Sharpe luck would produce ({p['sharpe_hurdle']:.2f})",
        "chips": [
            "Readers × document groups × holds × entries × level or shift",
            "Only the pre-registered one is confirmatory",
            "A null at the daily horizon fits a market that prices within minutes",
        ],
        "desk": "Search is charged for: the more variants, the higher the bar every one of them has to clear.",
        "source": "backtests table; deflated Sharpe ratio (Bailey and López de Prado 2014); evaluate/backtest.py.",
        "notes": f"We ran {len(bt)} variants and report all of them. With that many tries, the best Sharpe expected "
        "from "
        f"no skill is about {p['sharpe_hurdle']:.2f}; the deflated Sharpe ratio asks each variant to beat that. None "
        "does. The pre-registered trade is read on its own probabilistic Sharpe and its placebo, and neither is "
        "significant.",
        "link": "#/backtest",
        "visual": _table(["Measure", "Value", "Meaning"], rows, align="lrl", highlight=3),
    }


def forecast(c):
    f = c["forecast"]
    if not f:
        return None
    ins, oos = f["in_sample"], f["out_of_sample"]
    rows = [[x["name"], f"{x['beta']:+.3f}", f"{x['t']:.2f}", _p(x["p"])] for x in ins["coefs"]]
    rows += [
        ["R², market alone → with tone", f"{ins['r2_market']:.3f} → {ins['r2_both']:.3f}", "", ""],
        ["F-test of the three tone terms", f"F = {ins['f']:.2f}", "", _p(ins["p"])],
        [
            f"Real-time MSE from {oos['start'][:4]}: tone + market vs market",
            f"{oos['mse_both']:.3f} vs {oos['mse_market']:.3f}",
            "",
            f"{oos['p_boot']:.2f}",
        ],
    ]
    return {
        "id": "tech-forecast",
        "kicker": "Next decision, exploratory",
        "title": "Market predictors and the next decision",
        "subtitle": "No reduction in real-time forecast error from tone",
        "number": f"R² {ins['r2_market']:.2f}",
        "number_label": f"from the 3-month bill and 2-year over the policy rate alone, {f['n']} decisions",
        "chips": [
            "Decision coded −1, 0, +1; linear model, HC1 errors",
            "Inputs per standard deviation; all strictly before the decision day",
            f"Expanding window: each of {oos['n']} forecasts uses only earlier decisions",
        ],
        "desk": "Adding tone does not lower real-time forecast error in this sample; this result is exploratory.",
        "source": "evaluate/forecast.py; added after the results, charged to no hypothesis.",
        "notes": "Each decision since 2009 is modeled on the market's lean the evening before and on the tone of the "
        "latest minutes, recent speeches and the previous statement. In sample the tone terms are jointly significant "
        f"at the 5% level; R² is {ins['r2_market']:.3f} for the market and {ins['r2_both']:.3f} with tone. "
        "Forecasting each decision from 2017 with only earlier data, "
        "adding tone does not lower the error.",
        "link": "#/forecast",
        "visual": _table(["Input", "Per SD", "t", "p"], rows, align="lrrr"),
    }


def forward(c):
    fw = _meta(c["con"], "forward")
    if not fw or not fw.get("rules"):
        return None
    reads = {"level": "tone", "shift": "change in tone"}
    rows = [
        [
            TYPE_NAMES.get(r["doc_type"], r["doc_type"]),
            "Claude's comparison with the last decision"
            if r["method"].startswith("llmshift:")
            else reads[r["measure"]],
            f"{r['beta_bp_per_sd']:+.2f}",
            f"{r['t']:.2f}",
            f"{r['q']:.3f}",
        ]
        for r in fw["rules"]
    ]
    s, t = fw.get("summary", {}), fw.get("tilt", {})
    return {
        "id": "tech-forward",
        "kicker": "Forward test",
        "title": "After the freeze, nothing is re-fit",
        "subtitle": "The same rules run on new data only, as it is collected",
        "number": f"{len(rows)}",
        "number_label": f"frozen 2-year rules, one per document type, written on {fw['freeze']}",
        "chips": [
            f"Since the freeze: {s.get('hits', 0)} of {s.get('called', 0)} releases called right"
            if s.get("called")
            else f"No release scored since the {fw['freeze']} freeze yet",
            f"The pre-registered trade: {t.get('active_bp', 0):+.1f} bp over {t.get('days', 0)} trading days"
            if t.get("days")
            else "The pre-registered trade starts at the first close after the freeze",
            "A one-sided binomial test from 10 releases; no verdict before a year",
        ],
        "desk": "Rules and coefficients were frozen before these releases; no post-freeze refitting.",
        "source": "evaluate/forward.py; data/forward/rules.json (written once); fomc run leaves the research frozen.",
        "notes": "On 21 October 2026 the research was frozen. For each document type the strongest surviving 2-year "
        "relationship was written to a file with its coefficient and the in-sample mean and SD of its tone measure. "
        "Every evening each new release gets a predicted move beside its actual one, and the pre-registered trade runs "
        "through the backtest's own code, counted from the first close after the freeze.",
        "link": "#/forward",
        "visual": _table(["Type", "Reads", "bp per SD", "t", "q"], rows, align="llrrr"),
    }


# -------------------------------------------------------------------- systems
def store(c):
    rows = [
        [
            "collect",
            "Fed calendar and pages, cached by URL",
            "documents, full-text index, committee",
            "never: always runs",
        ],
        ["market", "FRED (Treasury fallback), Yahoo, New York Fed", "yields, etf_prices, policy_rates", "once a day"],
        ["events", "documents, yields, ETF closes", "events, decisions", "inputs unchanged"],
        ["baselines", "texts, labels, saved readers", "scores, validity", "texts, code, records unchanged"],
        ["llm-sync", "data/llm/*.json", "llm_records, scores", "records unchanged"],
        ["audit", "masked, repeated and re-read records", "meta.audit", "records unchanged"],
        ["evaluate", "scores, events, yields", "event_study, event_curves", "frozen since the freeze"],
        ["backtest", "scores, events, ETF closes", "backtests, backtest_curves", "frozen"],
        ["forecast", "scores, decisions, yields", "meta.forecast", "frozen"],
        ["forward", "the same, after the freeze", "meta.forward", "inputs unchanged"],
    ]
    return {
        "id": "tech-store",
        "layout": "wide",
        "kicker": "Store and pipeline",
        "title": "Ten stages, one SQLite store",
        "subtitle": "Stages talk only through the store and rerun only when their inputs change",
        "desk": f"{c['tables']} tables, schema v4 with automatic migrations; every stage run is logged in "
        "pipeline_runs.",
        "desk_label": "The store",
        "source": "src/fomc/db.py (schema, migrations), store.py, cli.py (fomc run, fingerprints); System › Pipeline.",
        "notes": "fomc run walks ten stages in order. Each stage's inputs are hashed, files, code and the parts of the "
        "settings it reads, and the stage is skipped when the hash matches the last run. Since the freeze the research "
        "stages are skipped regardless, unless asked to unfreeze. Full-text search is an FTS5 index over the documents "
        "table without duplicating text.",
        "link": "#/pipeline",
        "visual": _table(["Stage", "Reads", "Writes", "Skipped when"], rows, align="llll"),
    }


def serving(c):
    f = c["facts"]
    return {
        "id": "tech-serving",
        "layout": "wide",
        "kicker": "Serving",
        "title": "One read-only API serves everything",
        "subtitle": "Read-only and keyless: dashboard, unified story, feed and exports",
        "desk": "The hosted app holds no key: settings, scoring and labeling are locked by FOMC_PUBLIC=1.",
        "desk_label": "Security",
        "source": "FastAPI, gzip, ETags; vanilla JavaScript with ECharts; headless Chrome for slides (slides.py).",
        "notes": f"FastAPI serves {c['endpoints']} JSON endpoints; every read carries a validator, so an unchanged "
        "response costs a 304. The front end has no build step. The deck is rendered by parallel headless Chrome into "
        "one unified story with PDF and editable PowerPoint exports. An Atom feed gives each new document with its "
        "reading.",
        "link": "#/system",
        "visual": {
            "kind": "tiles",
            "tiles": [
                [f"{c['endpoints']}", "JSON endpoints; reads revalidate by ETag, a 304 when unchanged"],
                ["/feed.xml", "Atom feed: lean, percentile and the Fed's words for each new document"],
                ["0", "build steps: vanilla JavaScript, ECharts, self-hosted fonts and icons"],
                ["Reproduce", "make setup, make demo-data, then make serve. The supplied snapshot needs no API key."],
                ["One story", "Introduction and technical detail; PDF and editable PowerPoint exports"],
                [f"{f.get('raw_files', 0):,}", "source files cached by URL, so nothing is downloaded twice"],
            ],
        },
    }


def deploy(c):
    cap = settings()["llm"]["monthly_cap_usd"]
    return {
        "id": "tech-deploy",
        "layout": "wide",
        "kicker": "Deployment and operations",
        "title": "Automated refresh and spending guards",
        "subtitle": "Configured schedules, spending caps and checks for missing data",
        "desk": "A refresh that stops bringing things in fails loudly: GitHub emails the owner.",
        "desk_label": "Operations",
        "source": "GitHub Actions (.github/workflows/refresh.yml), Cloud Build, Artifact Registry, Cloud Run us-east4, "
        "Firebase Hosting, Cloud Scheduler; docs/OPERATIONS.md.",
        "notes": "A workflow is configured for every evening and the afternoon of a statement or minutes, after a "
        "fifteen-second check. It refreshes data, scores what is new under the caps, runs the forward test, then signs "
        "in to Google Cloud without a key and rolls out a new revision. A strict check fails the run if a scheduled "
        "release never arrives. The service scales to zero, kept warm by a free scheduler ping. These are configured "
        "controls; verify the workflow and cloud build's terminal state before treating a refresh as successful.",
        "link": "#/system",
        "visual": {
            "kind": "steps",
            "steps": [
                ["Trigger", "Configured: 7:30 p.m. ET daily; 2:25 p.m. ET on release afternoons; every main push"],
                ["Refresh", f"documents and prices; Claude on what is new, at most 40 jobs and {cap:.0f} USD a month"],
                ["Build", "keyless sign-in (workload identity federation); Cloud Build to Artifact Registry"],
                ["Serve", "Cloud Run, 1 vCPU, 1 GiB, 0 to 3 instances, warm by a free ping; fedtone.web.app"],
                ["Guard", "fomc doctor --strict: statements, minutes, prices and readings must keep arriving"],
                ["Cap", "a 1 USD budget unlinks billing through Pub/Sub and a function"],
            ],
        },
    }


def tests(c):
    # what pytest collects in this revision (scripts/test_inventory.py; the hosted image has no tests/ to count)
    try:
        by = json.loads(INVENTORY.read_text())["by_file"]
    except (OSError, ValueError, KeyError):
        by = c["facts"].get("tests_by_file") or {}
    if not by:
        return None
    what = {
        "test_timing.py": "release windows, holidays, entries that earn only later",
        "test_text_and_scoring.py": "cleaning, sentences, dictionary signs, quote checks",
        "test_scorer_offline.py": "the scoring engine against a stub client, no key",
        "test_store_api.py": "store, migrations, API, public mode, feed, the decks",
        "test_research.py": "decisions, false discovery, PSR and DSR, event panels",
        "test_forecast.py": "the next-decision inputs never look ahead",
        "test_forward.py": "the freeze: returns after it only, rules that cannot move",
        "test_finetune.py": "fine-tuning bookkeeping, without PyTorch",
        "test_ops.py": "release days, the monthly cap, drift, the strict check",
        "test_members.py": "quoted biographies, shifts in tone, what changed",
        "test_duration.py": "duration sizing, prior-only signals, source badges, input checks",
        "test_submission.py": "the code archive, the four deliverables, this test count",
    }
    rows = [[name.removeprefix("test_").removesuffix(".py"), n, what.get(name, "")] for name, n in by.items()]
    rows.sort(key=lambda r: -r[1])
    total = sum(by.values())
    return {
        "id": "tech-tests",
        "kicker": "Tests",
        "title": f"{total} offline tests, no model calls",
        "subtitle": "Checks cover timing, scoring, statistics, the API, operations and delivery",
        "number": f"{total}",
        "number_label": "tests that pytest collects in this revision; none needs a key or calls a model",
        "chips": [
            "Locked versions in requirements.lock, one file for every OS",
            "A guard keeps the research stack out of the hosted image",
            "Lint and a front-end check run beside the tests",
        ],
        "desk": "The rules that make a result trustworthy, like no look-ahead, are tests, not intentions.",
        "source": "Counts: pytest --collect-only on this revision (src/fomc/test_inventory.json). make test runs them; "
        "the CI workflow also runs make lint.",
        "notes": f"{total} tests run offline on this revision. The duration tests check the sizing identities, "
        "prior-only signals and input validation. The timing suite holds the no-look-ahead rules. The "
        "scoring engine is tested against a stub client, so the suite never spends money. The research tests check "
        "Benjamini-Hochberg against statsmodels and the Sharpe statistics. The operations tests cover the release-day "
        "check, the cap, drift and the strict freshness check.",
        "link": "#/pipeline",
        "visual": _table(["Suite", "Tests", "Guards"], rows, align="lrl"),
    }


def codemap(c):
    rows = [
        ["collect.py, textclean.py, http.py", "find, fetch and clean every Fed document; cache by URL"],
        ["market.py, align.py, policy.py", "yields and ETFs; release windows and entries; decisions and redlines"],
        ["llm/ provider, rubric, scorer", "credentials; the versioned rubric; jobs, batches, records, evidence checks"],
        ["dictionary, supervised, embeddings", "the three baselines; finetune.py and roberta.py, the references"],
        ["evaluate/", "validity, event_study, backtest, forecast, forward"],
        ["audit.py, labels.py", "memorization and drift checks; team labels shared through git"],
        ["db.py, store.py", "SQLite schema v4, migrations, persistence"],
        ["api.py, web/", "the read-only API, the dashboard and the feed"],
        ["story.py, story_technical.py, slides.py", "both decks from the store; PowerPoint and outlines"],
        ["cli.py", "the fomc command: run, llm-*, finetune, forward, drift, doctor, slides"],
    ]
    return {
        "id": "tech-codemap",
        "layout": "wide",
        "kicker": "Code map",
        "title": "Where each piece lives",
        "subtitle": "One package, one store, one command",
        "desk": "One package, one store, one command: make run rebuilds every number, make slides both decks.",
        "desk_label": "Start here",
        "source": "src/fomc/; docs/ARCHITECTURE.md, DESIGN.md, OPERATIONS.md.",
        "notes": "A map for the next person. Everything is one Python package with one store and one command. The "
        "architecture document has the details; the operations runbook says what runs when and how to fix it.",
        "link": "#/pipeline",
        "visual": _table(["Module", "Role"], rows, align="ll"),
    }


def slides(c) -> list:
    return [
        cover(c), agenda(c),
        divider(0), corpus(c), windows(c),
        divider(1), rubric_slide(c), engine(c), evidence(c), baselines(c), search(c), mps(c), validity_tests(c),
        confusions(c), reliability(c),
        divider(2), event_spec(c), robustness(c), backtest_math(c), selection(c), forecast(c), forward(c),
        divider(3), store(c), serving(c), deploy(c), tests(c), codemap(c),
        closing(c),
    ]  # fmt: skip
