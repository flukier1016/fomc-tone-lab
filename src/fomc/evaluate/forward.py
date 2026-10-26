"""Forward test: the frozen rules, on data that did not exist when they were frozen.

The research was frozen on `forward.freeze` (config/settings.yaml): the hypotheses, the trade and every coefficient.
From then on two checks run every evening on new data only, and nothing is re-fit.

* The pre-registered duration tilt (H3): Claude's reading of minutes and speeches, entry at the second close, a
  five-day hold, costs on every change, run by the backtest's own functions (signals standardized against earlier
  documents only). Its returns count from the first close after the freeze.
* The release-day relationship (H2): for each document type, the strongest 2-year relationship of Claude's tone that
  survived false-discovery control, with its in-sample coefficient and the in-sample mean and SD of the tone measure.
  The first run after the freeze writes these rules, and the trade's reader, to data/forward/rules.json (committed);
  every later run reads that file, so neither a rerun of the event study nor a new reader can move them. Each
  release after the freeze gets a predicted 2-year move (coefficient times standardized tone) beside its actual move
  over the release window; the score is how often the direction was right.

Small samples: no p-value before 10 releases, and no verdict before a year of data.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from .. import db
from ..config import DATA, settings
from . import backtest
from .event_study import build_panel

MIN_FOR_P = 10
RULES = DATA / "forward" / "rules.json"  # the H2 rules as frozen, written once


def freeze_date() -> pd.Timestamp:
    return pd.Timestamp(settings()["forward"]["freeze"])


def tilt(events: pd.DataFrame, scores: dict[str, pd.DataFrame], etfs: pd.DataFrame, primary: dict) -> dict:
    """The pre-registered trade, run exactly as in the backtest, with returns counted after the freeze. `primary`
    names the frozen reader (`method`); without one, the first Claude reader, as the backtest picks it."""
    method = primary.get("method") or next((m for m in scores if m.startswith(primary["method_prefix"])), None)
    if method not in scores or etfs.empty:
        return {}
    freeze = freeze_date()
    sig = backtest.signals(events, scores[method], primary["doc_types"], primary["entry"])
    ret = backtest.overlay(backtest.positions(sig, etfs.index, primary["hold"]), etfs)
    after = ret[ret.index > freeze]
    active = backtest.tilt_scale() * after
    new = sig[pd.to_datetime(sig["entry"]) > freeze]
    return {
        "method": method,
        "days": len(after),
        "signals": len(new),
        "hit_rate": backtest.hit_rate(new, etfs, primary["hold"]) if len(new) else None,
        "return_bp": round(float(after.sum() * 1e4), 2),  # the IEF-minus-SHY overlay, one unit at most
        "active_bp": round(float(active.sum() * 1e4), 2),  # on the aggregate-bond portfolio, duration +/- 1 year
        "curve": [[d.strftime("%Y-%m-%d"), round(float(v) * 1e4, 3)] for d, v in active.cumsum().items()],
        "recent": [
            {
                "doc_id": s.doc_id,
                "doc_type": s.doc_type,
                "entry": pd.Timestamp(s.entry).strftime("%Y-%m-%d"),
                "z": round(float(s.z), 3),
                "position": round(float(s.theta), 3),
            }
            for s in new.sort_values("entry").tail(12).itertuples()
        ],
    }


def _measure(
    events: pd.DataFrame, scores: dict[str, pd.DataFrame], decisions: set[str], doc_type: str, method: str, kind: str
) -> pd.DataFrame:
    """The tone measure a rule reads, per document in release order: the score (level) or its change since the
    previous document of the type (shift); statements are compared decision with decision, as in the event study."""
    if method not in scores:
        return pd.DataFrame(columns=["doc_id", "avail_ts", "x"])
    d = events.loc[events["doc_type"] == doc_type, ["doc_id", "avail_ts"]].merge(scores[method], on="doc_id")
    if doc_type == "statement":
        d = d[d["doc_id"].isin(decisions)]
    d = d.sort_values(["avail_ts", "doc_id"]).reset_index(drop=True)
    d["x"] = d["score"].diff() if kind == "shift" else d["score"]
    return d.dropna(subset=["x"])[["doc_id", "avail_ts", "x"]]


def frozen(con, events, scores, decisions, primary: dict) -> dict:
    """What the forward test runs, as frozen: the trade with its reader named, and the H2 rules. Read from
    data/forward/rules.json, or written there now (once) from the backtest's primary and the event study."""
    if RULES.exists():
        return json.loads(RULES.read_text())
    method = next((m for m in scores if m.startswith(primary["method_prefix"])), None)
    out = {
        "freeze": settings()["forward"]["freeze"],
        "tilt": {**primary, "method": method},
        "rules": rules(con, events, scores, decisions),
    }
    RULES.parent.mkdir(parents=True, exist_ok=True)
    RULES.write_text(json.dumps(out, indent=1) + "\n")
    return out


def rules(con, events, scores, decisions) -> list[dict]:
    """The H2 rules as the event study stands: per document type, the strongest surviving 2-year relationship of
    Claude's tone, with the in-sample mean and SD of its measure."""
    es = db.query(
        con,
        "SELECT doc_type, method, regressor, beta_bp_per_sd, t, q_bh, n FROM event_study WHERE sample = 'all' "
        "AND control = 'none' AND outcome = 'd2y' AND q_bh < 0.10 AND (method LIKE 'llm:%' OR method LIKE "
        "'llmshift:%') AND doc_type IN ('statement', 'minutes', 'presser', 'speech')",
    )
    freeze, out = freeze_date(), []
    for doc_type, g in es.groupby("doc_type"):
        r = g.loc[g["t"].abs().idxmax()]
        m = _measure(events, scores, decisions, doc_type, r["method"], r["regressor"])
        before = m.loc[pd.to_datetime(m["avail_ts"]) <= freeze, "x"]
        if len(before) < 12:
            continue
        out.append(
            {
                "doc_type": doc_type,
                "method": r["method"],
                "measure": r["regressor"],
                "beta_bp_per_sd": round(float(r["beta_bp_per_sd"]), 4),
                "t": round(float(r["t"]), 3),
                "q": round(float(r["q_bh"]), 4),
                "mean": float(before.mean()),
                "sd": float(before.std()),
                "n": int(r["n"]),
            }
        )
    return out


def releases(events, scores, yields, decisions, frozen: list[dict], panel: pd.DataFrame | None = None) -> list[dict]:
    """Every release after the freeze that a rule reads, with its predicted and actual 2-year move."""
    freeze = freeze_date()
    if panel is None:
        panel = build_panel(events, yields, {})
    moves = panel[panel["group"] == panel["doc_type"]].set_index("doc_id")["d2y"]
    out = []
    for r in frozen:
        m = _measure(events, scores, decisions, r["doc_type"], r["method"], r["measure"])
        for d in m[pd.to_datetime(m["avail_ts"]) > freeze].itertuples():
            if d.doc_id not in moves.index or pd.isna(moves[d.doc_id]):
                continue  # the window has not closed yet
            z = (d.x - r["mean"]) / r["sd"]
            predicted, actual = r["beta_bp_per_sd"] * z, float(moves[d.doc_id])
            out.append(
                {
                    "doc_id": d.doc_id,
                    "doc_type": r["doc_type"],
                    "date": pd.Timestamp(d.avail_ts).strftime("%Y-%m-%d"),
                    "method": r["method"],
                    "measure": r["measure"],
                    "z": round(float(z), 3),
                    "predicted_bp": round(float(predicted), 2),
                    "actual_bp": round(actual, 2),
                    "hit": bool(np.sign(predicted) == np.sign(actual)) if predicted and actual else None,
                }
            )
    return sorted(out, key=lambda x: (x["date"], x["doc_id"]))


def summary(rows: list[dict]) -> dict:
    called = [r for r in rows if r["hit"] is not None]
    hits = sum(r["hit"] for r in called)
    out = {"releases": len(rows), "called": len(called), "hits": hits}
    if len(called) >= MIN_FOR_P:  # one-sided: is the direction right more often than a coin?
        out["p"] = float(binomtest(hits, len(called), 0.5, alternative="greater").pvalue)
    return out


def run(con, events, scores, etfs, yields, decisions: set[str], primary: dict) -> dict:
    plan = frozen(con, events, scores, decisions, primary)
    rows = releases(events, scores, yields, decisions, plan["rules"])
    return {
        "freeze": plan["freeze"],
        "as_of": etfs.index.max().strftime("%Y-%m-%d") if len(etfs) else None,
        "tilt": tilt(events, scores, etfs, plan["tilt"]),
        "rules": plan["rules"],
        "releases": rows,
        "summary": summary(rows),
    }
