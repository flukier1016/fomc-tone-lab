"""Is a Fed statement or set of minutes out this afternoon? The release-day refresh asks before installing anything.

Statements come out at 2 p.m. in New York on the decision day, minutes at 2 p.m. three weeks later. The dates come
from the shipped store (deploy/fomc.db.gz): the scheduled decision dates the last refresh saw on the Fed's calendar,
and every past statement's meeting. Only the standard library, so the check takes seconds. Writes run=true or
run=false for GitHub Actions; the reason goes to stderr.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

STORE = Path(__file__).with_name("fomc.db.gz")
MINUTES_LAG = dt.timedelta(days=21)


def due(now: dt.datetime, decisions: set[str]) -> str | None:
    """'statement' or 'minutes' if one came out at 2 p.m. today and it is now between 2:00 and 3:20 p.m. in New York
    (one of the two afternoon runs fits, in daylight time or in winter; a late start still counts), else None."""
    if not (dt.time(14, 0) <= now.time() < dt.time(15, 20)):
        return None
    today = now.date()
    if today.isoformat() in decisions:
        return "statement"
    if (today - MINUTES_LAG).isoformat() in decisions:
        return "minutes"
    return None


def decisions(store: Path = STORE) -> set[str]:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp.write(gzip.decompress(store.read_bytes()))
        tmp.flush()
        con = sqlite3.connect(tmp.name)
        row = con.execute("SELECT value FROM meta WHERE key = 'upcoming_meetings'").fetchone()
        dates = set(json.loads(row[0])) if row else set()
        sql = "SELECT meeting_date FROM documents WHERE doc_type = 'statement' AND meeting_date IS NOT NULL"
        dates |= {r[0] for r in con.execute(sql)}
        con.close()
    return dates


if __name__ == "__main__":
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    what = due(now, decisions())
    print(f"{now:%Y-%m-%d %H:%M} in New York: " + (f"{what} out today" if what else "nothing due"), file=sys.stderr)
    print(f"run={'true' if what else 'false'}")
