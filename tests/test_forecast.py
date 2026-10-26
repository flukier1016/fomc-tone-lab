"""The next-decision test sees only what was public before each decision."""

import pandas as pd
import pytest

from fomc import db
from fomc.evaluate import forecast

LLM = "llm:claude-opus-5-5:v1"


@pytest.fixture()
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    db.init(c)
    docs = [
        ("statement_20200129", "statement", "2020-01-29"),
        ("statement_20200318", "statement", "2020-03-18"),
        ("statement_20200429", "statement", "2020-04-29"),
        ("minutes_20200129", "minutes", "2020-02-19"),
        ("minutes_20200318", "minutes", "2020-04-08"),
        ("speech_a", "speech", "2020-03-01"),
        ("speech_b", "speech", "2020-03-18"),  # the decision day itself: too late for that decision
        ("speech_c", "speech", "2020-04-10"),
    ]
    db.upsert(c, "documents", pd.DataFrame(docs, columns=["doc_id", "doc_type", "release_date"]).assign(note=None))
    decisions = [
        ("statement_20200129", "2020-01-29", 0, 0, 1.50, 1.75),
        ("statement_20200318", "2020-03-18", -1, -150, 0.00, 0.25),
        ("statement_20200429", "2020-04-29", 0, 0, 0.00, 0.25),
    ]
    cols = ["doc_id", "release_date", "action", "change_bp", "range_low", "range_high"]
    db.upsert(c, "decisions", pd.DataFrame(decisions, columns=cols))
    yields = [  # the decision-day closes (9.99) must never be used
        ("2020-01-28", 1.55, 1.45),
        ("2020-01-29", 9.99, 9.99),
        ("2020-03-17", 0.20, 0.40),
        ("2020-03-18", 9.99, 9.99),
        ("2020-04-28", 0.10, 0.20),
        ("2020-04-29", 9.99, 9.99),
    ]
    db.upsert(c, "yields", pd.DataFrame(yields, columns=["date", "t3m", "t2y"]))
    scores = {
        "statement_20200129": 0.1,
        "statement_20200318": -0.8,
        "statement_20200429": -0.5,
        "minutes_20200129": 0.2,
        "minutes_20200318": -0.6,
        "speech_a": -0.3,
        "speech_b": -0.5,
        "speech_c": -0.4,
    }
    db.upsert(c, "scores", pd.DataFrame({"method": LLM, "doc_id": list(scores), "score": list(scores.values())}))
    c.commit()
    yield c
    c.close()


def test_each_decision_sees_only_what_came_before(con):
    panel = forecast.build_panel(con, LLM).set_index("doc_id")
    # January has no earlier minutes or statement: dropped rather than filled with later information
    assert list(panel.index) == ["statement_20200318", "statement_20200429"]
    march = panel.loc["statement_20200318"]
    assert march.lean_3m == pytest.approx((0.20 - 1.625) * 100)  # the 17 March close, over the range before the cut
    assert march.minutes == pytest.approx(0.2)  # January's minutes, released in February
    assert march.speeches == pytest.approx(-0.3)  # the speech on the decision day is left out
    assert march.statement == pytest.approx(0.1)  # the previous statement
    april = panel.loc["statement_20200429"]
    assert april.lean_2y == pytest.approx((0.20 - 0.125) * 100)
    assert april.speeches == pytest.approx((-0.3 - 0.5 - 0.4) / 3)
    assert april.statement == pytest.approx(-0.8)
