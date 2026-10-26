"""The four hypotheses, judged once.

The Home page (GET /api/findings) and the Story's answers slide both read these verdicts, so a headline can never
disagree with the numbers behind it. Every value comes from the store; a hypothesis whose results are missing is
left out rather than guessed.
"""

from __future__ import annotations

import json

import pandas as pd

from . import db

BASELINES = ("dictionary", "supervised", "embedding")  # what H1 was stated against; FOMC-RoBERTa is a reference
GROUPS = {"statement": "statement", "minutes": "minutes", "presser": "press conference", "speech": "speech"}
TENORS = {
    "d3m": "3-month bill",
    "d2y": "2-year",
    "d5y": "5-year",
    "d10y": "10-year",
    "d30y": "30-year",
    "dslope": "2s10s",
}


def _meta(con, key: str):
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def summary(con) -> list[dict]:
    """One card per hypothesis: the claim, the verdict, one number and the sentence that explains it."""
    cards = []
    val = db.query(con, "SELECT method, macro_f1, n FROM validity ORDER BY macro_f1 DESC")
    llm, base = val[val["method"].str.startswith("llm:")], val[val["method"].isin(BASELINES)]
    if len(llm) and len(base):
        f1, f1_base = float(llm["macro_f1"].iloc[0]), float(base["macro_f1"].max())
        tests = [t for t in _meta(con, "validity_tests") or [] if t["method"] in BASELINES]
        lead = min(tests, key=lambda t: t["f1_diff"]) if tests else None  # against the closest baseline
        sure = lead is None or lead["p_boot"] < 0.05
        cards.append(
            {
                "key": "h1",
                "label": "H1 · Measurement",
                "claim": "Claude matches public expert labels better than the stated baselines",
                "verdict": "Supported" if f1 > f1_base and sure else "Mixed" if f1 > f1_base else "Not supported",
                "value": f"{f1:.2f}",
                "unit": f"vs {f1_base:.2f}",
                "detail": f"macro-F1 on {int(llm['n'].iloc[0])} expert-labeled sentences"
                + (f"; the lead is larger than chance ({_p(lead['p_boot'])})" if lead and sure else "")
                + "; public labels may be in training; no post-cutoff human test was run",
                "link": "#/validity",
            }
        )
    es = db.query(con, "SELECT doc_type, method, regressor, outcome, t, q_bh FROM event_study WHERE q_bh IS NOT NULL")
    if len(es):
        survive = es[es["q_bh"] < 0.10]
        top = es.loc[es["t"].abs().idxmax()]
        cards.append(
            {
                "key": "h2",
                "label": "H2 · Information",
                "claim": "Tone is associated with release-window Treasury moves",
                "verdict": "Supported" if len(survive) else "Not supported",
                "value": f"{len(survive)}",
                "unit": f"of {len(es)} tests",
                "detail": "survive false-discovery control; strongest: "
                f"{GROUPS.get(top['doc_type'], top['doc_type'])} tone {top['regressor']} on the "
                f"{TENORS.get(top['outcome'], top['outcome'])}, t = {top['t']:.2f}",
                "link": "#/event-study",
            }
        )
    prim = db.query(con, "SELECT sharpe, psr, placebo_p FROM backtests WHERE is_primary = 1")
    if len(prim):
        p = prim.iloc[0]
        placebo = p["placebo_p"]
        ok = p["sharpe"] > 0 and (p["psr"] or 0) >= 0.95 and (pd.isna(placebo) or placebo <= 0.05)
        cards.append(
            {
                "key": "h3",
                "label": "H3 · Tradability",
                "claim": "A next-day duration tilt on tone beats chance",
                "verdict": "Supported" if ok else "Not supported",
                "value": f"{p['sharpe']:.2f}".replace("-", "−"),
                "unit": "Sharpe",
                "detail": "pre-registered trade, after costs"
                + (f"; shuffled scores do as well (p = {placebo:.2f})" if pd.notna(placebo) and not ok else ""),
                "link": "#/backtest",
            }
        )
    audit = _meta(con, "audit") or {}
    if audit.get("identify") and audit.get("invariance"):
        exact = audit["identify"].get("statement", next(iter(audit["identify"].values())))["exact_month"]
        corr = audit["invariance"]["corr_stance_score"]
        same = corr >= 0.9
        cards.append(
            {
                "key": "h4",
                "label": "H4 · Contamination",
                "claim": "Masked scores are stable; recognition risk remains",
                "verdict": ("Mixed" if exact >= 0.5 else "Supported") if same else "Not supported",
                "value": f"r = {corr:.2f}",
                "unit": "",
                "detail": "scores with and without names and dates agree"
                + (f", though Claude still dates {exact:.0%} of masked statements" if exact >= 0.5 else ""),
                "link": "#/validity",
            }
        )
    return cards


def verdicts(con) -> dict[str, str]:
    return {c["key"]: c["verdict"] for c in summary(con)}
