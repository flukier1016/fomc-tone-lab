"""Persistence: stage outputs into the SQLite store, and back out for analysis.

Method names in the `scores` table:
  dictionary, supervised          baselines
  llm:<model>:<rubric>            LLM level score (stance_score, -1..+1)
  llmshift:<model>:<rubric>       LLM tone shift versus the previous document (-2..+2)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import db
from .config import INTERIM, LLM_DIR, settings

YIELD_COLS = {"3 Mo": "t3m", "2 Yr": "t2y", "5 Yr": "t5y", "10 Yr": "t10y", "30 Yr": "t30y"}


def save_documents(con, index: pd.DataFrame) -> int:
    df = index.copy()
    df["text"] = [
        (INTERIM / "texts" / f"{d}.txt").read_text() if (INTERIM / "texts" / f"{d}.txt").exists() else None
        for d in df["doc_id"]
    ]
    n = db.upsert(con, "documents", df)
    con.execute("INSERT INTO documents_fts (documents_fts) VALUES ('rebuild')")  # re-index from documents
    con.commit()
    return n


def save_market(con, yields: pd.DataFrame, etfs: pd.DataFrame) -> None:
    y = yields.rename(columns=YIELD_COLS).reset_index().rename(columns={"index": "date", "Date": "date"})
    y["date"] = pd.to_datetime(y["date"]).dt.strftime("%Y-%m-%d")
    db.upsert(con, "yields", y[["date", *YIELD_COLS.values()]])
    e = etfs.reset_index().rename(columns={"index": "date", "Date": "date"})
    e["date"] = pd.to_datetime(e["date"]).dt.strftime("%Y-%m-%d")
    db.upsert(con, "etf_prices", e[["date", *[c for c in ("SHY", "IEI", "IEF", "TLT", "AGG") if c in e]]])


def save_events(con, events: pd.DataFrame, yields: pd.DataFrame) -> int:
    ev = events.copy()
    for col, tenor in (("d2y_bp", "2 Yr"), ("d10y_bp", "10 Yr")):
        y = yields[tenor]
        ev[col] = [
            100 * (y.get(post) - y.get(pre))
            if pd.notna(pre) and pd.notna(post) and post in y.index and pre in y.index
            else None
            for pre, post in zip(ev["ust_pre"], ev["ust_post"])
        ]
    cols = [
        "doc_id",
        "doc_type",
        "avail_ts",
        "ust_pre",
        "ust_post",
        "ust_window_days",
        "etf_entry",
        "etf_entry_next",
        "d2y_bp",
        "d10y_bp",
    ]
    for c in ("avail_ts", "ust_pre", "ust_post", "etf_entry", "etf_entry_next"):
        ev[c] = pd.to_datetime(ev[c]).dt.strftime("%Y-%m-%d %H:%M").where(ev[c].notna(), None)
    return db.upsert(con, "events", ev[cols])


def save_scores(con, method: str, df: pd.DataFrame, replace: bool = True) -> int:
    """A method's scores; `replace` drops its earlier rows first, otherwise the rows are added or updated."""
    extra = [c for c in df.columns if c not in ("doc_id", "score")]
    out = pd.DataFrame(
        {
            "method": method,
            "doc_id": df["doc_id"],
            "score": df["score"],
            "details": [
                json.dumps({c: (None if pd.isna(v) else v) for c, v in zip(extra, row)}, default=str)
                for row in df[extra].itertuples(index=False, name=None)
            ],
            "updated_at": db.now(),
        }
    )
    if not replace:
        return db.upsert(con, "scores", out)
    return db.replace_where(con, "scores", "method = ?", (method,), out)


def load_scores(con, drop_low_relevance: bool = True) -> dict[str, pd.DataFrame]:
    df = db.query(con, "SELECT method, doc_id, score, details FROM scores")
    out = {}
    for method, g in df.groupby("method"):
        if drop_low_relevance and method.startswith("llm:"):
            rel = g["details"].map(lambda d: json.loads(d or "{}").get("policy_relevance"))
            g = g[rel != "low"]
        out[method] = g[["doc_id", "score"]].reset_index(drop=True)
    return out


def sync_llm(con) -> dict:
    """Mirror every JSON record under data/llm into llm_records, and LLM scores into `scores`."""
    from .llm import rubric
    from .llm.scorer import level_scores, shift_scores

    prices = settings()["llm"]["prices_per_mtok"]
    disc = settings()["llm"]["batch_discount"]
    rows = []
    for p in sorted(LLM_DIR.glob("*/*/*/*.json")):
        r = json.loads(p.read_text())
        u = r.get("usage", {})
        price = prices.get(r["model_requested"], {"input": 0, "output": 0})
        inp = (
            (u.get("input_tokens") or 0)
            + 1.25 * (u.get("cache_creation_input_tokens") or 0)
            + 0.1 * (u.get("cache_read_input_tokens") or 0)
        )
        mult = disc if r.get("batch_id") else 1.0
        ev = (r.get("checks") or {}).get("evidence") or {}
        rows.append(
            {
                "path": str(Path(p).relative_to(LLM_DIR)),
                "key": r["key"],
                "mode": r["mode"],
                "model": r["model_requested"],
                "rubric_version": r["rubric_version"],
                "run_tag": r.get("run_tag", ""),
                "status": r["status"],
                "message_id": r.get("message_id"),
                "request_id": r.get("request_id"),
                "batch_id": r.get("batch_id"),
                "stop_reason": r.get("stop_reason"),
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "cache_read_tokens": u.get("cache_read_input_tokens"),
                "cost_usd": mult * (inp * price["input"] + (u.get("output_tokens") or 0) * price["output"]) / 1e6,
                "evidence_share": ev.get("share"),
                "created_at": r.get("created_at"),
                "parsed": json.dumps(r.get("parsed"), ensure_ascii=False),
            }
        )
    db.upsert(con, "llm_records", pd.DataFrame(rows))
    current = {r["path"] for r in rows}  # a record moved to another folder must not count twice
    stale = [(p,) for (p,) in con.execute("SELECT path FROM llm_records") if p not in current]
    con.executemany("DELETE FROM llm_records WHERE path = ?", stale)
    con.commit()
    models = {r["model"] for r in rows}
    summary = {"records": len(rows), "models": sorted(models)}
    for model in models:
        lv = level_scores(model)
        if len(lv):
            save_scores(con, f"llm:{model}:{rubric.RUBRIC_VERSION}", lv)
        sh = shift_scores(model)
        if len(sh):
            save_scores(con, f"llmshift:{model}:{rubric.RUBRIC_VERSION}", sh.rename(columns={"shift_score": "score"}))
        summary[model] = {"level": len(lv), "shift": len(sh)}
    from . import labels

    summary["team_labels"] = labels.sync_llm(con, sorted(models))
    return summary


def save_backtests(con, table: pd.DataFrame, curves: dict[str, pd.Series]) -> None:
    """Variant summaries as rows; each daily return series as one float32 blob (40 rows, not 180,000)."""
    import numpy as np

    db.upsert(con, "backtests", table)
    con.execute("DELETE FROM backtest_curves")
    rows = [
        (run_id, ret.index[0].strftime("%Y-%m-%d"), len(ret), ret.to_numpy(dtype=np.float32).tobytes())
        for run_id, ret in curves.items()
        if len(ret)
    ]
    con.executemany("INSERT INTO backtest_curves VALUES (?, ?, ?, ?)", rows)
    con.commit()


def load_curve(con, run_id: str) -> pd.Series:
    import numpy as np

    row = con.execute("SELECT start_date, n, ret FROM backtest_curves WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return pd.Series(dtype=float)
    dates = [
        r[0] for r in con.execute("SELECT date FROM etf_prices WHERE date >= ? ORDER BY date LIMIT ?", (row[0], row[1]))
    ]
    return pd.Series(np.frombuffer(row[2], dtype=np.float32)[: len(dates)], index=dates)
