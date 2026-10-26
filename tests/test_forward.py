"""The forward test counts only what happened after the freeze, with rules that cannot move once written."""

import numpy as np
import pandas as pd
import pytest

from fomc import db
from fomc.evaluate import backtest, forward

LLM = "llm:claude-opus-5-5:v1"
PRIMARY = {"method_prefix": "llm:", "doc_types": ["minutes"], "entry": "etf_entry_next", "hold": 5}
DAYS = pd.bdate_range("2026-01-02", "2026-12-31")


def _events(n: int = 40) -> pd.DataFrame:
    avail = [DAYS[5 + 6 * i] + pd.Timedelta(hours=14) for i in range(n)]  # one release about every six trading days
    return pd.DataFrame(
        {
            "doc_id": [f"minutes_{i:02d}" for i in range(n)],
            "doc_type": "minutes",
            "avail_ts": avail,
            "etf_entry_next": [DAYS[DAYS.get_loc(a.normalize()) + 1] for a in avail],
        }
    )


def _scores(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(3)
    return {LLM: pd.DataFrame({"doc_id": events["doc_id"], "score": rng.uniform(-1, 1, len(events)).round(2)})}


def _etfs() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    walk = lambda s: 100 * np.exp(np.cumsum(rng.normal(0, s, len(DAYS))))  # noqa: E731
    return pd.DataFrame({"IEF": walk(0.004), "SHY": walk(0.001)}, index=DAYS)


def test_the_trade_counts_returns_after_the_freeze_only():
    events, etfs = _events(), _etfs()
    scores = _scores(events)
    out = forward.tilt(events, scores, etfs, PRIMARY)
    sig = backtest.signals(events, scores[LLM], ["minutes"], "etf_entry_next")
    ret = backtest.overlay(backtest.positions(sig, DAYS, 5), etfs)  # the backtest's own path, untouched
    after = ret[ret.index > pd.Timestamp("2026-10-21")]
    assert out["days"] == len(after) and out["return_bp"] == pytest.approx(after.sum() * 1e4, abs=0.01)
    assert out["signals"] == int((sig["entry"] > pd.Timestamp("2026-10-21")).sum()) > 0
    assert out["curve"][0][0] > "2026-10-21"
    assert out["curve"][-1][1] == pytest.approx(backtest.tilt_scale() * after.sum() * 1e4, abs=0.01)


def test_each_release_is_scored_against_the_frozen_rule():
    events = pd.DataFrame(
        {
            "doc_id": ["minutes_a", "minutes_b", "minutes_c", "minutes_d", "minutes_e"],
            "doc_type": "minutes",
            "avail_ts": pd.to_datetime(
                ["2026-09-02 14:00", "2026-11-04 14:00", "2026-11-25 14:00", "2026-12-16 14:00", "2026-12-30 14:00"]
            ),  # fmt: skip
        }
    )
    scores = {LLM: pd.DataFrame({"doc_id": events["doc_id"], "score": [0.9, 0.5, -0.25, 0.3, 0.8]})}
    rule = {"doc_type": "minutes", "method": LLM, "measure": "level", "beta_bp_per_sd": 2.0, "mean": 0.0, "sd": 0.5}
    panel = pd.DataFrame(
        {
            "doc_id": ["minutes_a", "minutes_b", "minutes_c", "minutes_d"],  # e: its window has not closed
            "doc_type": "minutes",
            "group": "minutes",
            "d2y": [5.0, 3.0, 1.0, 0.0],
        }
    )
    rows = forward.releases(events, scores, None, set(), [rule], panel=panel)
    assert [r["doc_id"] for r in rows] == ["minutes_b", "minutes_c", "minutes_d"]  # a is before the freeze
    assert [r["predicted_bp"] for r in rows] == [2.0, -1.0, 1.2]
    assert [r["hit"] for r in rows] == [True, False, None]  # no move, no call
    assert forward.summary(rows) == {"releases": 3, "called": 2, "hits": 1}  # too few for a p-value


def test_rules_once_written_do_not_move(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(forward, "RULES", tmp_path / "rules.json")
    con = db.connect()
    db.init(con)
    row = {"doc_type": "minutes", "method": LLM, "regressor": "level", "outcome": "d2y", "sample": "all"}
    db.upsert(con, "event_study", pd.DataFrame([{**row, "control": "none", "beta_bp_per_sd": 1.5, "t": 3.0,
                                                 "q_bh": 0.02, "n": 40}]))  # fmt: skip
    events = _events()
    first = forward.frozen(con, events, _scores(events), set(), PRIMARY)
    assert first["tilt"]["method"] == LLM and len(first["rules"]) == 1
    assert first["rules"][0]["beta_bp_per_sd"] == 1.5 and first["rules"][0]["sd"] > 0
    con.execute("UPDATE event_study SET beta_bp_per_sd = 9.9")  # the event study is rerun later
    later = {"llm:a-newer-model:v1": _scores(events)[LLM], **_scores(events)}  # and a new reader is added
    assert forward.frozen(con, events, later, set(), PRIMARY) == first
    con.close()
