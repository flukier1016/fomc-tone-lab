"""The rules that keep the study free of look-ahead."""

import pandas as pd

from fomc import align
from fomc.evaluate import backtest

DAYS = pd.bdate_range("2024-01-29", "2024-02-09")  # Mon 29 Jan .. Fri 9 Feb
UST = align.closes(DAYS, "15:30")
ETF = align.closes(DAYS, "16:00")


def ts(s):
    return pd.Timestamp(s)


def test_statement_at_2pm_belongs_to_the_same_day():
    assert align.first_close_after(ts("2024-01-31 14:00"), UST) == ts("2024-01-31")
    assert align.last_close_before(ts("2024-01-31 14:00"), UST) == ts("2024-01-30")


def test_release_after_the_close_moves_the_next_day():
    assert align.first_close_after(ts("2024-01-31 19:00"), UST) == ts("2024-02-01")
    assert align.last_close_before(ts("2024-01-31 19:00"), UST) == ts("2024-01-31")


def test_release_exactly_at_the_close_is_not_in_that_close():
    assert align.first_close_after(ts("2024-01-31 15:30"), UST) == ts("2024-02-01")


def test_weekend_release_moves_to_monday():
    assert align.first_close_after(ts("2024-02-03 10:00"), UST) == ts("2024-02-05")


def test_press_conference_gets_a_two_day_window():
    index = pd.DataFrame(
        [
            {
                "doc_id": "presser_20240131",
                "doc_type": "presser",
                "release_date": "2024-01-31",
                "release_time_et": "15:30",
                "info_start_et": "14:30",
            }
        ]
    )
    ev = align.event_table(index, DAYS, DAYS).iloc[0]
    assert ev.ust_pre == ts("2024-01-30") and ev.ust_post == ts("2024-02-01") and ev.ust_window_days == 2
    assert ev.etf_entry == ts("2024-01-31") and ev.etf_entry_next == ts("2024-02-01")


def test_a_speech_stamped_near_the_close_counts_as_after_it():
    """Feed timestamps are approximate: a speech within the slack of a close moves to the next one; a document
    whose time is printed in it does not."""
    row = {"release_date": "2024-01-31", "release_time_et": "15:00", "info_start_et": "15:00"}
    index = pd.DataFrame(
        [
            {**row, "doc_id": "speech_a", "doc_type": "speech", "time_source": "speech_json"},
            {**row, "doc_id": "statement_x", "doc_type": "statement", "time_source": "document_text"},
        ]
    )
    ev = align.event_table(index, DAYS, DAYS).set_index("doc_id")
    assert ev.loc["speech_a", "ust_post"] == ts("2024-02-01") and ev.loc["speech_a", "etf_entry"] == ts("2024-02-01")
    assert ev.loc["statement_x", "ust_post"] == ts("2024-01-31") and ev.loc["statement_x", "etf_entry"] == ts(
        "2024-01-31"
    )


def test_position_earns_only_after_entry_close():
    sig = pd.DataFrame([{"entry": ts("2024-01-31"), "theta": 1.0}])
    pos = backtest.positions(sig, DAYS, hold=2)
    assert pos[ts("2024-01-30")] == 0 and pos[ts("2024-01-31")] == 1 and pos[ts("2024-02-01")] == 1
    assert pos[ts("2024-02-02")] == 0
    lagged = pos.shift(1)  # exposure applied to each day's return
    assert lagged[ts("2024-01-31")] == 0  # entry day's own return is not earned
    assert lagged[ts("2024-02-01")] == 1 and lagged[ts("2024-02-02")] == 1


def test_signal_uses_only_earlier_documents():
    rows = [
        {
            "doc_id": f"d{i}",
            "doc_type": "minutes",
            "avail_ts": ts("2020-01-01") + pd.Timedelta(days=30 * i),
            "etf_entry": ts("2020-01-02") + pd.Timedelta(days=30 * i),
        }
        for i in range(20)
    ]
    events = pd.DataFrame(rows)
    scores = pd.DataFrame({"doc_id": [f"d{i}" for i in range(20)], "score": list(range(19)) + [1000.0]})
    sig = backtest.signals(events, scores, ["minutes"], "etf_entry")
    before = sig[sig.doc_id != "d19"]["z"]
    scores.loc[19, "score"] = -1000.0  # change only the last document
    after = backtest.signals(events, scores, ["minutes"], "etf_entry")
    assert (after[after.doc_id != "d19"]["z"].to_numpy() == before.to_numpy()).all()
