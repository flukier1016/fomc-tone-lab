"""Map each document's public moment to market closes, without look-ahead.

Rule: a document can only move prices observed at a close strictly after the
moment it became public. All times are U.S. Eastern.

  * UST window: from the last Treasury close (3:30 p.m.) strictly before the
    first information leaves the Fed, to the first close strictly after the
    full document is public. A 2:00 p.m. statement gives a one-day window; a
    press conference (2:30-3:30 p.m.) straddles the close and gets two days.
  * ETF entry: the first ETF close (4:00 p.m.) strictly after the document is
    public; the conservative variant waits one more trading day.
  * Approximate times: a speech's time comes from the Board's feed, not from the
    document, so a speech within `ambiguous_minutes` of a close is treated as
    released after it (its window and entry move to the next close).
"""

from __future__ import annotations

import pandas as pd

from . import collect, market
from .config import PROCESSED, settings


def closes(days: pd.DatetimeIndex, close_et: str) -> pd.DatetimeIndex:
    hh, mm = map(int, close_et.split(":"))
    return pd.DatetimeIndex(days).normalize() + pd.Timedelta(hours=hh, minutes=mm)


def first_close_after(ts: pd.Timestamp, close_ts: pd.DatetimeIndex) -> pd.Timestamp | None:
    i = close_ts.searchsorted(ts, side="right")
    return close_ts[i].normalize() if i < len(close_ts) else None


def last_close_before(ts: pd.Timestamp, close_ts: pd.DatetimeIndex) -> pd.Timestamp | None:
    i = close_ts.searchsorted(ts, side="left") - 1
    return close_ts[i].normalize() if i >= 0 else None


def event_table(index: pd.DataFrame, ust_days: pd.DatetimeIndex, etf_days: pd.DatetimeIndex) -> pd.DataFrame:
    cfg = settings()["markets"]
    ust_close = closes(ust_days, cfg["ust_close_et"])
    etf_close = closes(etf_days, cfg["etf_close_et"])
    slack = pd.Timedelta(minutes=cfg.get("ambiguous_minutes", 0))
    rows = []
    for d in index.itertuples():
        avail = pd.Timestamp(f"{d.release_date} {d.release_time_et}")
        info = pd.Timestamp(f"{d.release_date} {d.info_start_et}")
        late = avail + (slack if getattr(d, "time_source", "") == "speech_json" else pd.Timedelta(0))
        pre = last_close_before(info, ust_close)
        post = first_close_after(late, ust_close)
        entry = first_close_after(late, etf_close)
        later = etf_days[etf_days > entry] if entry is not None else etf_days[:0]
        rows.append(
            {
                "doc_id": d.doc_id,
                "doc_type": d.doc_type,
                "avail_ts": avail,
                "ust_pre": pre,
                "ust_post": post,
                "ust_window_days": int(((ust_days > pre) & (ust_days <= post)).sum())
                if pre is not None and post is not None
                else None,
                "etf_entry": entry,
                "etf_entry_next": later[0] if len(later) else None,
            }
        )
    return pd.DataFrame(rows)


def build() -> pd.DataFrame:
    docs = collect.usable()
    events = event_table(docs, market.load_yields().index, market.load_etfs().index)
    events = events.merge(docs[["doc_id", "speaker", "speaker_role", "time_source"]], on="doc_id")
    events.to_csv(PROCESSED / "events.csv", index=False)
    return events


def load_events() -> pd.DataFrame:
    return pd.read_csv(
        PROCESSED / "events.csv", parse_dates=["avail_ts", "ust_pre", "ust_post", "etf_entry", "etf_entry_next"]
    )
