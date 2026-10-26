"""Running it unattended: the release-day check before the afternoon refresh."""

import datetime as dt
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location(
    "release_day", Path(__file__).resolve().parents[1] / "deploy" / "release_day.py"
)
release_day = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_day)

NY = ZoneInfo("America/New_York")
DECISIONS = {"2026-09-16", "2026-10-28"}


def at(day: str, hh: int, mm: int) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}").replace(tzinfo=NY)


def test_statements_and_minutes_are_due_only_on_their_afternoon():
    assert release_day.due(at("2026-10-28", 14, 25), DECISIONS) == "statement"
    assert release_day.due(at("2026-10-07", 14, 25), DECISIONS) == "minutes"  # three weeks after 16 September
    assert release_day.due(at("2026-10-07", 15, 5), DECISIONS) == "minutes"  # a late start still counts
    assert release_day.due(at("2026-10-28", 13, 25), DECISIONS) is None  # winter's first run, before the release
    assert release_day.due(at("2026-10-28", 15, 25), DECISIONS) is None  # summer's second run: already done
    assert release_day.due(at("2026-10-22", 14, 25), DECISIONS) is None  # an ordinary day


def test_the_monthly_cap_counts_this_months_direct_calls_only(tmp_path, monkeypatch):
    import json

    import pytest

    from fomc.llm import rubric, scorer

    root = tmp_path / "claude-opus-5-5" / rubric.RUBRIC_VERSION / "level"
    root.mkdir(parents=True)

    def record(name: str, created: str, batch: bool, output_tokens: int):
        usage = {"input_tokens": 0, "output_tokens": output_tokens}
        rec = {
            "mode": "level",
            "status": "ok",
            "batch_id": "b1" if batch else None,
            "created_at": created,
            "usage": usage,
        }
        (root / f"{name}.json").write_text(json.dumps(rec))

    record("a", "2026-11-03T10:00:00+00:00", False, 50_000)  # $1.00 at $20 per million output tokens
    record("b", "2026-11-20T10:00:00+00:00", False, 25_000)  # $0.50
    record("c", "2026-11-05T10:00:00+00:00", True, 50_000)  # a Message Batch: a backfill started by hand
    record("d", "2026-10-31T23:00:00+00:00", False, 50_000)  # last month
    monkeypatch.setattr(scorer, "LLM_DIR", tmp_path)
    assert scorer.month_spend("claude-opus-5-5", "2026-11-21") == pytest.approx(1.5)


def test_scheduled_scoring_stops_at_the_monthly_cap(monkeypatch, capsys):
    from types import SimpleNamespace

    import pandas as pd

    from fomc import cli
    from fomc.llm import scorer

    sent = []

    class Stub:
        model = "claude-opus-5-5"

        def __init__(self, model=None):
            pass

        def done(self, job):
            return False

        def call(self, job):
            sent.append(job.key)
            return {"status": "ok"}

    spend = iter([4.0, 4.6, 5.2])  # before the first call, then after each one (the cap is 5.0)
    monkeypatch.setattr(scorer, "Scorer", Stub)
    monkeypatch.setattr(scorer, "month_spend", lambda model: next(spend))
    monkeypatch.setattr(scorer, "usage_summary", lambda model: pd.DataFrame({"cost_usd": [33.0]}))
    monkeypatch.setattr(cli.collect, "usable", lambda: pd.DataFrame({"doc_id": []}))
    jobs = [SimpleNamespace(key=f"doc{i}") for i in range(4)]
    monkeypatch.setattr(cli, "_jobs", lambda mode, docs, types: jobs if mode == "level" else [])
    monkeypatch.setattr(cli.store, "sync_llm", lambda con: "synced")
    cli.cmd_llm_update(SimpleNamespace(model=None, max=40), con=None)
    assert sent == ["doc0", "doc1"]
    assert "reached the cap of $5.00: 2 jobs wait" in capsys.readouterr().out


def test_monthly_rereads_flag_a_reader_that_moved(tmp_path, monkeypatch):
    import json

    from fomc import audit
    from fomc.llm import rubric, scorer

    monkeypatch.setattr(scorer, "LLM_DIR", tmp_path)
    monkeypatch.setattr(audit, "LLM_DIR", tmp_path)
    monkeypatch.setattr(audit, "ANCHORS", tmp_path / "anchors.json")
    root = tmp_path / "claude-opus-5-5" / rubric.RUBRIC_VERSION

    def read(mode: str, doc: str, score: float, stance: int):
        parsed = {"stance_score": score, "overall_stance": stance, "confidence": 0.8, "policy_relevance": "high"}
        parsed.update({d: 0 for d in rubric.DIMENSIONS})
        rec = {
            "key": doc,
            "status": "ok",
            "parsed": parsed,
            "checks": {"evidence": {"share": 1.0}},
            "model_served": "m",
        }
        (root / mode).mkdir(parents=True, exist_ok=True)
        (root / mode / f"{doc}.json").write_text(json.dumps(rec))

    docs = ["statement_1", "minutes_1", "presser_1", "speech_1"]
    for i, d in enumerate(docs):
        read("level", d, 0.2 * i, 1)
        read("level_r2", d, 0.2 * i, 1)
        read("level_d202611", d, 0.2 * i + 0.01, 1)  # November: the same reading
        read("level_d202612", d, 0.2 * i - 0.3, 0)  # December: every document reads more dovish
    assert audit.drift_report("claude-opus-5-5") == {}  # no anchors chosen yet: nothing to compare
    assert audit.anchors("claude-opus-5-5") == ["statement_1", "minutes_1", "presser_1", "speech_1"]
    months = audit.drift_report("claude-opus-5-5")["months"]
    assert [m["month"] for m in months] == ["2026-11", "2026-12"]
    assert months[0]["drifted"] is False and months[0]["overall_stance_agreement"] == 1.0
    assert months[1]["drifted"] is True and months[1]["mean_abs_diff"] == 0.3
    assert audit.drift_tag("2027-01") == "d202701"


def test_after_the_freeze_the_research_stages_stay_as_reported(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fomc import cli, db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    con = db.connect()
    db.init(con)
    ran = []
    for name in ("audit", "evaluate", "backtest", "forecast", "forward"):
        monkeypatch.setitem(cli.COMMANDS, name, lambda a, con, name=name: ran.append(name))
    monkeypatch.setattr(cli, "_fingerprint", lambda stage, con, a: None)  # as if every input had changed
    monkeypatch.setattr(cli.labels, "import_files", lambda con: None)
    run = SimpleNamespace(start="audit", until="forward", force=False, placebo=False, unfreeze=False)
    cli.cmd_run(run, con)
    assert ran == ["audit", "forward"]  # the event study, the backtest and the forecast are not recomputed
    ran.clear()
    cli.cmd_run(SimpleNamespace(**{**vars(run), "unfreeze": True}), con)
    assert ran == ["audit", "evaluate", "backtest", "forecast", "forward"]
    con.close()


def test_a_store_that_quietly_stopped_growing_fails_the_strict_check(tmp_path, monkeypatch):
    import json

    import pandas as pd

    from fomc import cli, db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    con = db.connect()
    db.init(con)
    con.execute("INSERT INTO meta VALUES ('scheduled_meetings', ?)", (json.dumps(["2026-09-16", "2026-10-28"]),))
    docs = pd.DataFrame(
        [
            {"doc_id": "statement_20260916", "doc_type": "statement", "release_date": "2026-09-16", "note": None},
            {"doc_id": "speech_a", "doc_type": "speech", "release_date": "2026-10-20", "note": None},
        ]
    )
    db.upsert(con, "documents", docs)
    db.upsert(con, "yields", pd.DataFrame({"date": ["2026-10-29"], "t2y": [3.9]}))
    db.upsert(con, "etf_prices", pd.DataFrame({"date": ["2026-10-29"], "IEF": [95.0]}))
    con.commit()
    status = lambda day, **kw: {n: ok for n, ok, _ in cli.freshness(con, dt.date.fromisoformat(day), **kw)}  # noqa: E731
    got = status("2026-10-30")
    assert got["statements"] is False  # the 28 October statement never arrived
    assert got["minutes"] is False  # nor the minutes of 16 September, due on 7 October
    assert got["yields"] is True and got["etf_prices"] is True
    assert got["Claude"] is False  # a speech of 20 October still unread
    assert status("2026-10-30", cap_reached=True)["Claude"] is True  # the month's cap explains the wait
    assert status("2026-11-10")["yields"] is False  # market data stopped on 29 October
    assert status("2026-10-27")["statements"] is True  # before the meeting nothing is late
    con.close()


def test_a_meeting_that_has_passed_stays_on_the_schedule(tmp_path, monkeypatch):
    import json

    from fomc import cli, db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    con = db.connect()
    db.init(con)
    con.execute("INSERT INTO meta VALUES ('upcoming_meetings', ?)", (json.dumps(["2026-10-28", "2026-12-09"]),))
    cli.remember_schedule(con, ["2026-12-09", "2027-01-27"])  # after 28 October the calendar lists only later ones
    row = con.execute("SELECT value FROM meta WHERE key = 'scheduled_meetings'").fetchone()
    assert json.loads(row[0]) == ["2026-10-28", "2026-12-09", "2027-01-27"]
    con.close()


def test_after_the_freeze_the_baselines_score_only_new_documents(tmp_path, monkeypatch):
    """A classifier retrained on another machine moves in the last digits: the reported validity must not."""
    from types import SimpleNamespace

    import pandas as pd

    from fomc import cli, db, store
    from fomc.evaluate import validity
    from fomc.llm import scorer

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    con = db.connect()
    db.init(con)
    docs = pd.DataFrame({"doc_id": ["a", "b", "c"], "doc_type": "speech"})
    db.upsert(con, "documents", docs.assign(release_date="2026-10-20", note=None))
    for method in ("dictionary", "supervised", "embedding"):
        store.save_scores(con, method, pd.DataFrame({"doc_id": ["a", "b"], "score": [0.1, -0.2], "n_sentences": 3}))
    scored = []

    def score(ds, *_):
        scored.append(list(ds["doc_id"]))
        return pd.DataFrame({"doc_id": ds["doc_id"], "score": 0.9, "n_sentences": 3})

    class Embeddings:
        def train(self):
            return self

        def score_documents(self, ds, texts):
            return score(ds)

        def predict(self, sentences):
            return [2] * len(sentences)

    monkeypatch.setattr(cli, "settings", lambda: {"forward": {"freeze": "2026-10-21"}})
    monkeypatch.setattr(cli.collect, "usable", lambda: docs)
    monkeypatch.setattr(scorer, "texts_for", lambda ds: {d: "text" for d in ds["doc_id"]})
    monkeypatch.setattr(cli.dictionary, "score_documents", lambda ds, texts: score(ds))
    monkeypatch.setattr(cli.supervised, "train", lambda: "model")
    monkeypatch.setattr(cli.supervised, "score_documents", lambda model, ds, texts: score(ds))
    monkeypatch.setattr(cli.supervised, "load_tdw", lambda split: pd.DataFrame({"sentence": [], "label": []}))
    monkeypatch.setattr(cli.embeddings, "SentenceEmbeddings", Embeddings)
    monkeypatch.setattr(cli, "READERS", {})
    monkeypatch.setattr(cli.labels, "predict", lambda con, model, team: 0)
    measured = []
    monkeypatch.setattr(validity, "sentence_benchmark", lambda *a, **k: measured.append(1))
    cli.cmd_baselines(SimpleNamespace(), con)
    assert scored == [["c"], ["c"], ["c"]] and measured == []  # the new document only; validity untouched
    emb = store.load_scores(con)["embedding"].set_index("doc_id")["score"].to_dict()
    assert emb == {"a": 0.1, "b": -0.2, "c": 0.9}  # the reported scores stay
    con.close()
