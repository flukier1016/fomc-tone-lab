"""SQLite store: one file (data/fomc.db) that every stage writes and the API reads.

Why SQLite: zero setup for teammates, one portable file, readable by any SQLite
browser, and FTS5 full-text search over every Fed document out of the box.
The schema is versioned; `init()` is idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .config import DATA

DB_PATH = DATA / "fomc.db"
SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, meeting_date TEXT, release_date TEXT,
    release_time_et TEXT, time_source TEXT, info_start_et TEXT, url TEXT, speaker TEXT,
    speaker_role TEXT, title TEXT, n_words INTEGER, text_sha256 TEXT, note TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_documents_type_date ON documents (doc_type, release_date);

-- External-content FTS5: the index points at documents.text instead of storing a second copy.
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5 (
    title, speaker, text, content = 'documents', content_rowid = 'rowid', tokenize = 'porter unicode61');

-- Daily overnight rates from the New York Fed, and the Committee as of the latest minutes.
CREATE TABLE IF NOT EXISTS policy_rates (date TEXT PRIMARY KEY, effr REAL, sofr REAL);
CREATE TABLE IF NOT EXISTS committee (
    name TEXT PRIMARY KEY, status TEXT, board INTEGER, role TEXT, bank TEXT, fomc_vice_chair INTEGER, as_of TEXT);

CREATE TABLE IF NOT EXISTS yields (date TEXT PRIMARY KEY, t3m REAL, t2y REAL, t5y REAL, t10y REAL, t30y REAL);
CREATE TABLE IF NOT EXISTS etf_prices (date TEXT PRIMARY KEY, SHY REAL, IEI REAL, IEF REAL, TLT REAL, AGG REAL);

CREATE TABLE IF NOT EXISTS events (
    doc_id TEXT PRIMARY KEY REFERENCES documents (doc_id), doc_type TEXT, avail_ts TEXT,
    ust_pre TEXT, ust_post TEXT, ust_window_days INTEGER, etf_entry TEXT, etf_entry_next TEXT,
    d2y_bp REAL, d10y_bp REAL);

CREATE TABLE IF NOT EXISTS scores (
    method TEXT NOT NULL, doc_id TEXT NOT NULL REFERENCES documents (doc_id), score REAL,
    details TEXT, updated_at TEXT, PRIMARY KEY (method, doc_id));
CREATE INDEX IF NOT EXISTS ix_scores_doc ON scores (doc_id);

CREATE TABLE IF NOT EXISTS llm_records (
    path TEXT PRIMARY KEY, key TEXT, mode TEXT, model TEXT, rubric_version TEXT, run_tag TEXT,
    status TEXT, message_id TEXT, request_id TEXT, batch_id TEXT, stop_reason TEXT,
    input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cost_usd REAL,
    evidence_share REAL, created_at TEXT, parsed TEXT);
CREATE INDEX IF NOT EXISTS ix_llm_key ON llm_records (key, mode);

CREATE TABLE IF NOT EXISTS llm_batches (
    batch_id TEXT PRIMARY KEY, model TEXT, mode TEXT, n_jobs INTEGER, status TEXT,
    created_at TEXT, collected_at TEXT);

CREATE TABLE IF NOT EXISTS validity (
    method TEXT PRIMARY KEY, n INTEGER, accuracy REAL, macro_f1 REAL, cohen_kappa REAL, updated_at TEXT);

-- sample: all | development | holdout; control: none | d3m (3-month bill, a surprise proxy) | decision.
-- q_bh: Benjamini-Hochberg q-value across the main grid (sample all, no control, release-window outcomes).
CREATE TABLE IF NOT EXISTS event_study (
    doc_type TEXT, method TEXT, regressor TEXT, outcome TEXT, sample TEXT, control TEXT, n INTEGER,
    beta_bp_per_sd REAL, t REAL, p REAL, q_bh REAL, r2 REAL, updated_at TEXT,
    PRIMARY KEY (doc_type, method, regressor, outcome, sample, control));
-- Average cumulative 2-year move around releases, by tercile of tone.
CREATE TABLE IF NOT EXISTS event_curves (
    doc_type TEXT, method TEXT, regressor TEXT, bucket TEXT, day INTEGER, mean_bp REAL, se_bp REAL, n INTEGER,
    PRIMARY KEY (doc_type, method, regressor, bucket, day));

-- The decision in each FOMC statement and how its wording changed from the previous decision.
CREATE TABLE IF NOT EXISTS decisions (
    doc_id TEXT PRIMARY KEY REFERENCES documents (doc_id), meeting_date TEXT, release_date TEXT,
    action INTEGER, change_bp INTEGER, range_low REAL, range_high REAL, prev_doc_id TEXT,
    similarity REAL, words_added INTEGER, words_removed INTEGER, n_words INTEGER);

-- Team annotation: sentences sampled after the model's knowledge cutoff, labels -1 dovish, 0 neutral, +1 hawkish.
CREATE TABLE IF NOT EXISTS label_items (
    item_id INTEGER PRIMARY KEY, doc_id TEXT REFERENCES documents (doc_id), position INTEGER,
    sentence TEXT NOT NULL UNIQUE, context_before TEXT, context_after TEXT, batch TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS labels (
    item_id INTEGER NOT NULL REFERENCES label_items (item_id), annotator TEXT NOT NULL, label INTEGER NOT NULL,
    created_at TEXT, PRIMARY KEY (item_id, annotator));
CREATE TABLE IF NOT EXISTS label_predictions (
    item_id INTEGER NOT NULL REFERENCES label_items (item_id), method TEXT NOT NULL, label INTEGER,
    PRIMARY KEY (item_id, method));

CREATE TABLE IF NOT EXISTS backtests (
    run_id TEXT PRIMARY KEY, method TEXT, doc_types TEXT, hold INTEGER, entry TEXT, is_primary INTEGER,
    n_signals INTEGER, hit_rate REAL, ann_return REAL, ann_vol REAL, sharpe REAL, max_drawdown REAL,
    t_nw REAL, sharpe_development REAL, sharpe_holdout REAL, sharpe_post_cutoff REAL,
    placebo_p REAL, placebo_sharpe_95 REAL, psr REAL, dsr REAL, n_trials INTEGER, sharpe_hurdle REAL,
    signal TEXT, active_bp REAL, tracking_bp REAL, updated_at TEXT);
-- One row per variant: daily returns as a float32 blob aligned to etf_prices dates (from start_date).
CREATE TABLE IF NOT EXISTS backtest_curves (
    run_id TEXT PRIMARY KEY, start_date TEXT, n INTEGER, ret BLOB);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT, status TEXT, started_at TEXT,
    finished_at TEXT, detail TEXT);
"""


def store_bytes(path: Path | None = None) -> int:
    """Size of the store: the database file plus its write-ahead log and shared-memory file."""
    path = Path(path or DB_PATH)
    return sum(
        p.stat().st_size
        for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"))
        if p.exists()
    )


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _migrate(con: sqlite3.Connection) -> None:
    row = con.execute("SELECT name FROM sqlite_master WHERE name = 'meta'").fetchone()
    version = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() if row else None
    if not version:
        return
    if int(version[0]) < 2:
        # v1 kept a second copy of every text inside the FTS table and one row per backtest day.
        con.executescript("DROP TABLE IF EXISTS documents_fts; DROP TABLE IF EXISTS backtest_returns;")
        con.executescript(SCHEMA)
        con.execute("INSERT INTO documents_fts (documents_fts) VALUES ('rebuild')")
        con.commit()
    if int(version[0]) < 3:
        # v3 adds samples, controls and q-values to the event study and PSR/DSR to the backtests. Both
        # tables are derived, so they are rebuilt: drop them and mark the stages that fill them as stale.
        con.executescript("DROP TABLE IF EXISTS event_study; DROP TABLE IF EXISTS backtests;")
        con.execute("DELETE FROM meta WHERE key IN ('fp:events', 'fp:baselines', 'fp:evaluate', 'fp:backtest')")
        con.commit()
    if int(version[0]) < 4:
        # v4 adds the AGG benchmark to ETF prices and portfolio columns to the backtests (rebuilt by the
        # next run, together with the market stage that fills AGG).
        cols = {r[1] for r in con.execute("PRAGMA table_info(etf_prices)")}
        if cols and "AGG" not in cols:
            con.execute("ALTER TABLE etf_prices ADD COLUMN AGG REAL")
        con.executescript("DROP TABLE IF EXISTS backtests;")
        con.execute("DELETE FROM meta WHERE key IN ('fp:market', 'fp:baselines', 'fp:evaluate', 'fp:backtest')")
        con.commit()


def init(con: sqlite3.Connection) -> None:
    _migrate(con)
    con.executescript(SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()


def checkpoint(con: sqlite3.Connection) -> None:
    """Fold the write-ahead log back into the main file so the store stays one compact file."""
    con.execute("PRAGMA optimize")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def vacuum(con: sqlite3.Connection) -> None:
    con.execute("INSERT INTO documents_fts (documents_fts) VALUES ('optimize')")
    con.commit()
    con.execute("VACUUM")
    checkpoint(con)


def query(con: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, con, params=params)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    return value


def upsert(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    cols = list(df.columns)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    rows = [tuple(_clean(v) for v in row) for row in df.itertuples(index=False, name=None)]
    con.executemany(sql, rows)
    con.commit()
    return len(rows)


def replace_where(con: sqlite3.Connection, table: str, where: str, params: tuple, df: pd.DataFrame) -> int:
    con.execute(f"DELETE FROM {table} WHERE {where}", params)
    return upsert(con, table, df)


@contextmanager
def stage(con: sqlite3.Connection, name: str):
    """Record a pipeline stage in pipeline_runs; the UI's Pipeline page reads this table."""
    cur = con.execute("INSERT INTO pipeline_runs (stage, status, started_at) VALUES (?, 'running', ?)", (name, now()))
    con.commit()
    run_id, detail = cur.lastrowid, {}
    try:
        yield detail
    except Exception as exc:
        con.execute(
            "UPDATE pipeline_runs SET status = 'failed', finished_at = ?, detail = ? WHERE id = ?",
            (now(), json.dumps({"error": str(exc)[:500]}), run_id),
        )
        con.commit()
        raise
    con.execute(
        "UPDATE pipeline_runs SET status = 'ok', finished_at = ?, detail = ? WHERE id = ?",
        (now(), json.dumps(detail, default=str), run_id),
    )
    con.commit()
