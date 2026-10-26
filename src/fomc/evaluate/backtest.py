"""Duration-tilt backtest with no look-ahead.

Instrument: the duration spread r = r(IEF) - r(SHY), long 7-10y Treasuries
against 1-3y. A hawkish document shortens duration (short the spread), a
dovish one extends it.

Timing, the part that decides whether a result is real:
  * the signal is standardized with the mean and SD of earlier documents of
    the same type only (expanding window), so no future score leaks in;
  * a position is set at the first ETF close after the document is public
    (or one day later, the conservative variant) and earns returns from the
    next day for `hold` trading days;
  * overlapping positions add up and are capped at one unit;
  * every change in position pays `cost_bp_per_side` on both legs.
Portfolio: the same overlay applied to a bond portfolio. Scaled so one unit
moves duration by `duration_budget_years` (IEF and SHY durations held
constant), it is the active return of an aggregate-bond (AGG) or Treasury
(IEI) portfolio whose duration is tilted by at most that many years.
Signals: the level of tone, or its shift since the previous document of the
same type (the brief's "tone shift between consecutive statements").
Inference: Newey-West t-statistic, and a placebo that shuffles the scores
across documents of the same type (the HW2 shuffled-control idea).
Selection: every variant is reported. The probabilistic Sharpe ratio (PSR)
is the confidence that a variant's true Sharpe is above zero, allowing for
skewed, fat-tailed returns; the deflated Sharpe ratio (DSR) raises the bar to
the Sharpe the best of N unskilled variants would show by luck (Bailey and
Lopez de Prado 2012, 2014). The pre-registered primary is read on its PSR,
every exploratory variant on its DSR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as st

from ..config import settings


def signals(
    events: pd.DataFrame, scores: pd.DataFrame, doc_types: list[str], entry_col: str, score_col: str = "score"
) -> pd.DataFrame:
    min_events = settings()["backtest"]["zscore_min_events"]
    ev = events[events["doc_type"].isin(doc_types)].merge(scores[["doc_id", score_col]], on="doc_id")
    ev = ev.dropna(subset=[score_col, entry_col]).sort_values("avail_ts")
    out = []
    for _, g in ev.groupby("doc_type"):
        s = g[score_col]
        mean = s.expanding().mean().shift(1)
        sd = s.expanding().std().shift(1)
        n = s.expanding().count().shift(1)
        z = ((s - mean) / sd).where(n >= min_events)
        out.append(g.assign(z=z))
    cols = ["doc_id", "doc_type", "avail_ts", entry_col, "z"]
    sig = pd.concat(out).dropna(subset=["z"]) if out else pd.DataFrame(columns=cols)  # no scores for these types
    sig["theta"] = -sig["z"].clip(-2, 2) / 2
    return sig[["doc_id", "doc_type", "avail_ts", entry_col, "z", "theta"]].rename(columns={entry_col: "entry"})


def positions(sig: pd.DataFrame, days: pd.DatetimeIndex, hold: int) -> pd.Series:
    """Exposure held at each close: the sum of active signals, capped at one unit."""
    pos = pd.Series(0.0, index=days)
    idx = {d: i for i, d in enumerate(days)}
    for s in sig.itertuples():
        i = idx.get(s.entry)
        if i is None:
            continue
        pos.iloc[i : i + hold] += s.theta
    return pos.clip(-1, 1)


def overlay(pos: pd.Series, etfs: pd.DataFrame) -> pd.Series:
    cfg = settings()["backtest"]
    spread = etfs[cfg["long_etf"]].pct_change() - etfs[cfg["short_etf"]].pct_change()
    gross = pos.shift(1) * spread.reindex(pos.index)
    cost = 2 * cfg["cost_bp_per_side"] / 1e4 * pos.diff().abs()
    return (gross - cost).fillna(0.0)


def stats(ret: pd.Series, hold: int) -> dict:
    ret = ret.dropna()
    active = ret[ret != 0]
    if len(active) < 20:
        return {"days": len(ret), "active_days": len(active)}
    nw = sm.OLS(ret.to_numpy(), np.ones(len(ret))).fit(cov_type="HAC", cov_kwds={"maxlags": hold})
    wealth = (1 + ret).cumprod()
    return {
        "days": len(ret),
        "active_days": len(active),
        "ann_return": ret.mean() * 252,
        "ann_vol": ret.std() * np.sqrt(252),
        "sharpe": ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan,
        "max_drawdown": (wealth / wealth.cummax() - 1).min(),
        "t_nw": nw.tvalues[0],
    }


def tilt_scale() -> float:
    """Overlay units per year of portfolio duration: one unit of IEF minus SHY moves duration this much."""
    cfg = settings()["backtest"]
    spread_duration = cfg["durations"][cfg["long_etf"]] - cfg["durations"][cfg["short_etf"]]
    return cfg["duration_budget_years"] / spread_duration


def shift_scores(scores: pd.DataFrame, events: pd.DataFrame, decisions: set[str] | None = None) -> pd.DataFrame:
    """Change in a method's score since the previous document of the same type that it scored. Given the policy
    decisions, a statement is compared only with the previous decision, never with a notice."""
    d = events[["doc_id", "doc_type", "avail_ts"]].merge(scores[["doc_id", "score"]], on="doc_id")
    if decisions is not None:
        d = d[(d["doc_type"] != "statement") | d["doc_id"].isin(decisions)]
    d = d.sort_values(["doc_type", "avail_ts", "doc_id"])
    d["score"] = d.groupby("doc_type")["score"].diff()
    return d.dropna(subset=["score"])[["doc_id", "score"]].reset_index(drop=True)


def hit_rate(sig: pd.DataFrame, etfs: pd.DataFrame, hold: int) -> float:
    cfg = settings()["backtest"]
    spread = (etfs[cfg["long_etf"]].pct_change() - etfs[cfg["short_etf"]].pct_change()).fillna(0)
    days = etfs.index
    idx = {d: i for i, d in enumerate(days)}
    hits = []
    for s in sig.itertuples():
        i = idx.get(s.entry)
        if i is None or i + hold >= len(days):
            continue
        fwd = spread.iloc[i + 1 : i + 1 + hold].sum()
        hits.append(np.sign(s.theta) == np.sign(fwd))
    return float(np.mean(hits)) if hits else np.nan


def run(
    events: pd.DataFrame,
    scores: pd.DataFrame,
    etfs: pd.DataFrame,
    doc_types: list[str],
    hold: int,
    entry_col: str = "etf_entry",
    score_col: str = "score",
    placebo: bool = True,
) -> dict:
    cfg = settings()
    sig = signals(events, scores, doc_types, entry_col, score_col)
    days = etfs.index
    ret = overlay(positions(sig, days, hold), etfs)
    out = {"n_signals": len(sig), "hit_rate": hit_rate(sig, etfs, hold), **stats(ret, hold)}
    active = tilt_scale() * ret.dropna()
    out["active_bp"] = float(active.mean() * 252 * 1e4)
    out["tracking_bp"] = float(active.std() * np.sqrt(252) * 1e4)
    for name, (lo, hi) in cfg["splits"].items():
        part = ret[(ret.index >= lo) & (ret.index <= hi)]
        out[f"sharpe_{name}"] = stats(part, hold).get("sharpe", np.nan)
    if placebo and "sharpe" in out:
        rng = np.random.default_rng(cfg["backtest"]["seed"])
        draws = []
        for _ in range(cfg["backtest"]["placebo_draws"]):
            shuffled = sig.copy()
            shuffled["theta"] = shuffled.groupby("doc_type")["theta"].transform(lambda t: rng.permutation(t.to_numpy()))
            draws.append(stats(overlay(positions(shuffled, days, hold), etfs), hold).get("sharpe", np.nan))
        draws = np.array(draws)
        out["placebo_p"] = float(np.mean(draws >= out["sharpe"]))
        out["placebo_sharpe_95"] = float(np.nanpercentile(draws, 95))
    out["returns"] = ret
    return out


EULER_GAMMA = 0.5772156649015329


def _daily_sharpe(ret: pd.Series) -> float:
    r = ret.dropna().to_numpy()
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd) if sd > 0 else np.nan


def probabilistic_sharpe(ret: pd.Series, benchmark: float = 0.0) -> float:
    """P(true Sharpe > benchmark) from the sample Sharpe, skewness and kurtosis; per-day units."""
    r = ret.dropna().to_numpy()
    if len(r) < 30 or r.std(ddof=1) == 0:
        return np.nan
    sr = r.mean() / r.std(ddof=1)
    skew, kurt = st.skew(r), st.kurtosis(r, fisher=False)
    var = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    return float(st.norm.cdf((sr - benchmark) * np.sqrt(len(r) - 1) / np.sqrt(max(var, 1e-12))))


def expected_max_sharpe(sharpes: np.ndarray, n_trials: int | None = None) -> float:
    """The Sharpe the best of N trials with no skill would show by luck; per-day units."""
    sharpes = np.asarray(sharpes, dtype=float)
    sharpes = sharpes[np.isfinite(sharpes)]
    n = n_trials or len(sharpes)
    if n < 2 or len(sharpes) < 2:
        return 0.0
    z = (1 - EULER_GAMMA) * st.norm.ppf(1 - 1 / n) + EULER_GAMMA * st.norm.ppf(1 - 1 / (n * np.e))
    return float(np.std(sharpes, ddof=1) * z)


def deflate(table: pd.DataFrame, curves: dict[str, pd.Series]) -> pd.DataFrame:
    """Add PSR, DSR, the number of trials and the luck hurdle (annualized) to every variant."""
    srs = np.array([_daily_sharpe(curves[r]) for r in table["run_id"]])
    hurdle = expected_max_sharpe(srs)
    out = table.copy()
    out["psr"] = [probabilistic_sharpe(curves[r]) for r in table["run_id"]]
    out["dsr"] = [probabilistic_sharpe(curves[r], hurdle) for r in table["run_id"]]
    out["n_trials"] = int(np.isfinite(srs).sum())
    out["sharpe_hurdle"] = hurdle * np.sqrt(252)
    return out
