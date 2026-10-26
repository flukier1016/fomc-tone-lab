"""User-selected duration scenarios, separate from the frozen research and its signals.

Dollar DV01 = market value * modified duration / 10,000. An equal-dollar
IEF/SHY overlay changes duration by weight * (D_IEF - D_SHY). Prices, carry,
convexity, spread risk and borrowing are deliberately not inferred here.

Sized by a document's rule, the change is theta * duration budget, as in the backtest, where one unit of signal moves
duration by the budget; a manual change is only capped by it. Costs are a round trip, both legs in and out, as the
backtest charges every change of position.
"""

from __future__ import annotations

import math

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

SOURCES = [
    {
        "label": "CME: modified duration and basis-point value",
        "url": "https://www.cmegroup.com/education/courses/introduction-to-treasuries/how-can-you-measure-risk-in-treasuries",
    }
]


class ScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    nav_usd: float = Field(default=1_000_000, gt=0, le=1e12)
    base_duration: float = Field(default=6, ge=0, le=30)
    duration_change: float = Field(default=-1, ge=-5, le=5)
    duration_budget: float = Field(default=1, ge=0, le=5)
    shock_bp: float = Field(default=50, ge=-500, le=500)
    cost_bp_per_side: float = Field(default=1, ge=0, le=100)
    signal_theta: float | None = Field(default=None, ge=-1, le=1)  # a document's rule: replaces duration_change


def assumptions(cfg: dict) -> dict:
    long, short = cfg["long_etf"], cfg["short_etf"]
    dl, ds = float(cfg["durations"][long]), float(cfg["durations"][short])
    if not (math.isfinite(dl) and math.isfinite(ds) and dl > ds >= 0):
        raise ValueError("The long instrument must have a finite duration above the short instrument.")
    return {
        "long_etf": long,
        "short_etf": short,
        "long_duration": dl,
        "short_duration": ds,
        "spread_duration": dl - ds,
        "duration_source": "Fixed research assumptions, not live ETF duration estimates",
        "pnl_method": "First-order, parallel yield shift; no convexity, carry, spread or financing adjustment",
        "execution_limit": "The negative leg requires holdings to sell or shorting capacity; neither is checked.",
        "sources": SOURCES,
    }


def scenario(body: ScenarioIn, cfg: dict) -> dict:
    a = assumptions(cfg)
    rule = body.signal_theta is not None
    requested = body.signal_theta * body.duration_budget if rule else body.duration_change
    change = max(-body.duration_budget, min(body.duration_budget, requested))
    weight = change / a["spread_duration"]
    notional = body.nav_usd * weight
    cost = 4 * abs(notional) * body.cost_bp_per_side / 10_000  # two legs, in and out
    before = body.nav_usd * body.base_duration / 10_000
    active = body.nav_usd * change / 10_000
    after = before + active

    def stress(shock: float) -> dict:
        original, incremental = -before * shock, -active * shock

        def cash(value: float) -> float:
            rounded = round(value, 2)
            return rounded if rounded else 0.0  # no negative zero in API money fields

        return {
            "shock_bp": shock,
            "base_pnl_usd": cash(original),
            "active_pnl_before_cost_usd": cash(incremental),
            "active_pnl_after_cost_usd": cash(incremental - cost),
            "portfolio_pnl_after_cost_usd": cash(original + incremental - cost),
        }

    def leg(ticker: str, value: float) -> dict:
        return {
            "ticker": ticker,
            "action": "buy" if value > 0 else "sell" if value < 0 else "none",
            "signed_notional_usd": round(value, 2),
        }

    return {
        "inputs": body.model_dump(),
        "assumptions": a,
        "sizing": "rule" if rule else "manual",
        "requested_duration_change": requested,
        "applied_duration_change": change,
        "budget_capped": change != requested,
        "target_duration": body.base_duration + change,
        "dv01_before_usd": round(before, 2),
        "dv01_active_usd": round(active, 2),
        "dv01_after_usd": round(after, 2),
        "overlay_weight": weight,
        "gross_notional_usd": round(2 * abs(notional), 2),
        "traded_notional_usd": round(4 * abs(notional), 2),
        "cost_basis": "Round trip: both legs bought or sold at entry and again at exit, as in the historical test",
        "cost_usd": round(cost, 2),
        "breakeven_shock_bp": -cost / active if active else None,
        "legs": [leg(a["long_etf"], notional), leg(a["short_etf"], -notional)],
        "selected": stress(body.shock_bp),
        "scenarios": [stress(s) for s in sorted({-100, -50, -25, 0, 25, 50, 100, body.shock_bp})],
    }


def document_context(frame: pd.DataFrame, doc_id: str | None, cfg: dict, primary: dict) -> dict | None:
    """Replay one document's frozen sizing rule using earlier eligible peers only.

    This is an isolated signal, not the backtest's combined position: that test
    adds overlapping trades and caps the total. Nothing is estimated or saved.
    """
    if frame.empty:
        return None
    frame = frame.copy()
    frame["stamp"] = pd.to_datetime(frame["avail_ts"], utc=True, errors="coerce")
    types = primary["doc_types"].split("+")
    usable = frame["score"].notna() & frame["relevance"].ne("low") & frame["stamp"].notna()
    if doc_id is None:
        pick = frame[usable & frame["doc_type"].isin(types) & frame[primary["entry"]].notna()]
        if pick.empty:
            pick = frame
        selected = pick.sort_values(["stamp", "doc_id"]).iloc[-1]
    else:
        pick = frame[frame["doc_id"] == doc_id]
        if pick.empty:
            return None
        selected = pick.iloc[0]
    # the backtest's history: same type, scored, policy-relevant, with an entry close; here strictly earlier releases
    alike = usable & frame["doc_type"].eq(selected["doc_type"]) & frame[primary["entry"]].notna()
    peers = frame[alike & frame["stamp"].lt(selected["stamp"])]
    same_time = int((alike & frame["stamp"].eq(selected["stamp"]) & frame["doc_id"].ne(selected["doc_id"])).sum())
    values = peers["score"].astype(float)
    n = len(values)
    sd = float(values.std()) if n > 1 else None
    mean = float(values.mean()) if n else None
    minimum = cfg["zscore_min_events"]
    reason = None
    if pd.isna(selected["score"]):
        reason = "No score from the frozen reader is available for this document."
    elif selected["relevance"] == "low":
        reason = "Low monetary-policy relevance; the research excludes this reading from trade signals."
    elif selected["doc_type"] not in types:
        reason = "The primary strategy trades minutes and speeches, not this document type."
    elif pd.isna(selected[primary["entry"]]):
        reason = "The required ETF entry close is not available in the stored market calendar."
    elif n < minimum:
        reason = f"Only {n} earlier eligible readings of this type; {minimum} are required."
    elif sd is None or not math.isfinite(sd) or sd <= 0:
        reason = "The earlier readings have no usable dispersion for a standardized signal."
    z = (float(selected["score"]) - mean) / sd if reason is None else None
    theta = max(-2, min(2, z)) * -0.5 if z is not None else None
    scope = "One document, earlier peers only. The historical backtest also combines overlapping trades."
    if same_time:
        scope += (
            f" {same_time} other document{'s' if same_time > 1 else ''} of this type came out at the same minute and "
            "is not counted as history here; the historical test's ordering may count one, so its z can differ "
            "slightly."
        )
    details = {
        k: (None if pd.isna(selected[k]) else selected[k])
        for k in (
            "doc_id",
            "doc_type",
            "release_date",
            "release_time_et",
            "title",
            "speaker",
            "url",
            "score",
            "avail_ts",
        )
    }
    return {
        "document": details,
        "method": primary["method"],
        "run_id": primary["run_id"],
        "entry_date": None if pd.isna(selected[primary["entry"]]) else selected[primary["entry"]],
        "hold_days": int(primary["hold"]),
        "history_n": n,
        "history_mean": mean,
        "history_sd": sd if sd is None or math.isfinite(sd) else None,
        "minimum_history": minimum,
        "eligible": reason is None,
        "reason": reason,
        "z": z,
        "theta": theta,
        "duration_budget_years": cfg["duration_budget_years"],
        "duration_change_years": theta * cfg["duration_budget_years"] if theta is not None else None,
        "same_time_peers": same_time,
        "scope": scope,
    }
