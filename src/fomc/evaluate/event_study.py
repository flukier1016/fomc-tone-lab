"""Event study: does tone explain the Treasury move over the release window?

For each document, the outcome is the change in par yields (basis points)
over its no-look-ahead window from align.py. Scores are standardized within
group, so a coefficient is "bp per one standard deviation of tone".

What is estimated, and why:
  * level and shift: the score itself, and its change from the previous
    document of the same type that the method scored, in order of release
    (markets read documents against each other); a statement is compared only
    with the previous policy decision, never with a notice such as a swap-line
    announcement or a framework review;
  * the term structure: 3m, 2y, 5y, 10y and 30y, plus the 2s10s slope;
  * placebo: the trading day before the window opens; tone should not
    "explain" a move that happened before the release;
  * drift: 5 and 20 trading days after the window closes;
  * beyond the decision: the same regression controlling for the 3-month bill
    over the window, a proxy for the near-term rate surprise (it over-controls
    if tone itself moves near-term expectations, so it is a robustness check),
    and, for statements and press conferences, for the change in the target
    range announced at that meeting (policy.py);
  * stability: development (2009-2019) and holdout (2020 onward) separately;
  * statements and the press conference: the statement window ends at the
    3:30 p.m. fix, after the press conference has begun, so statements are also
    estimated on meetings without a press conference and with the press
    conference's own tone as a control;
  * beyond word counts: Claude's tone with the TF-IDF classifier's tone of the
    same documents as a control (an encompassing regression);
  * multiple testing: Benjamini-Hochberg q-values across the main grid: the four
    document types (the Chair's and other members' speeches are subsets, reported
    outside the family), every method and regressor, the release-window outcomes.
Groups are the four document types plus speeches split into the Chair's and
the other Board members'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ..config import settings

TENORS = {"d3m": "3 Mo", "d2y": "2 Yr", "d5y": "5 Yr", "d10y": "10 Yr", "d30y": "30 Yr"}
MAIN = ["d3m", "d2y", "d5y", "d10y", "d30y", "dslope"]
DIAGNOSTIC = ["pre_d2y", "drift5_d2y", "drift20_d2y"]
GROUPS = ["statement", "minutes", "presser", "speech", "speech_chair", "speech_other"]
FAMILY = ["statement", "minutes", "presser", "speech"]  # the BH family; speech subsets would count speeches twice
ROBUST = ["d2y", "d5y", "d10y", "dslope"]
BASELINE = "supervised"  # the strongest word-count reader, used as a control for Claude


def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd and np.isfinite(sd) else s * 0


def _windows(events: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    pos = {d: i for i, d in enumerate(days)}
    ev = events.dropna(subset=["ust_pre", "ust_post"]).copy()
    ev["i0"] = ev["ust_pre"].map(pos)
    ev["i1"] = ev["ust_post"].map(pos)
    return ev.dropna(subset=["i0", "i1"]).astype({"i0": int, "i1": int})


def _groups(row) -> list[str]:
    out = [row.doc_type]
    if row.doc_type == "speech":
        out.append("speech_chair" if str(getattr(row, "speaker_role", "")) == "Chair" else "speech_other")
    return out


def build_panel(
    events: pd.DataFrame,
    yields: pd.DataFrame,
    scores: dict[str, pd.DataFrame],
    decisions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per (document, group): outcomes in bp and standardized tone per method.

    `decisions` (doc_id, meeting_date, change_bp) attaches the announced change in the target range
    to the statement and to the press conference of the same meeting.
    """
    ev = _windows(events, yields.index)
    by_meeting, decision_ids = {}, None
    if decisions is not None and len(decisions):
        dec = decisions.dropna(subset=["change_bp"])
        keys = pd.to_datetime(dec["meeting_date"]).dt.strftime("%Y%m%d")  # doc ids end in the meeting date
        by_meeting = dict(zip(keys, dec["change_bp"].astype(float)))
        decision_ids = set(dec["doc_id"])
    presser_meetings = {str(d).split("_")[-1][:8] for d in ev.loc[ev["doc_type"] == "presser", "doc_id"]}
    rows = []
    for e in ev.itertuples():
        i0, i1 = e.i0, e.i1
        if i0 < 1:
            continue
        meeting = str(e.doc_id).split("_")[-1][:8]
        base = {
            "doc_id": e.doc_id,
            "doc_type": e.doc_type,
            "date": e.ust_post,
            "avail_ts": getattr(e, "avail_ts", e.ust_post),
            "meeting": meeting if e.doc_type in ("statement", "presser") else None,
            "change_bp": np.nan,
        }
        if e.doc_type in ("statement", "presser"):
            base["change_bp"] = by_meeting.get(meeting, np.nan)
            base["presser_meeting"] = meeting in presser_meetings
        for name, col in TENORS.items():
            y = yields[col]
            base[name] = 100 * (y.iloc[i1] - y.iloc[i0])
        y2 = yields["2 Yr"]
        base["dslope"] = base["d10y"] - base["d2y"]
        base["pre_d2y"] = 100 * (y2.iloc[i0] - y2.iloc[i0 - 1])
        for h in (5, 20):
            base[f"drift{h}_d2y"] = 100 * (y2.iloc[i1 + h] - y2.iloc[i1]) if i1 + h < len(y2) else np.nan
        for g in _groups(e):
            rows.append({**base, "group": g})
    panel = pd.DataFrame(rows).sort_values(["group", "avail_ts", "doc_id"]).reset_index(drop=True)
    notice = (panel["group"] == "statement") & ~panel["doc_id"].isin(decision_ids or set(panel["doc_id"]))
    for method, sc in scores.items():
        panel[method] = panel["doc_id"].map(sc.set_index("doc_id")["score"])
        if method.startswith("llmshift:"):
            panel.loc[notice, method] = np.nan  # Claude's comparison only reads decision against decision
        scored = panel[panel[method].notna() & ~notice]
        panel[f"{method}__shift"] = scored.groupby("group")[method].diff()  # aligned on the index
        for c in (method, f"{method}__shift"):
            panel[c] = panel.groupby("group")[c].transform(_zscore)
    # the press conference's tone at the same meeting, beside each statement
    pr = panel[panel["group"] == "presser"].set_index("meeting")
    st = panel["group"] == "statement"
    for method in scores:
        for c in (method, f"{method}__shift"):
            panel.loc[st, f"{c}__presser"] = panel.loc[st, "meeting"].map(pr[c])
    return panel.sort_values("date").reset_index(drop=True)


def _fit(d: pd.DataFrame, y: str, xs: list[str]) -> dict | None:
    d = d[[y, *xs]].dropna()
    if len(d) < 15 or (d[xs].std() == 0).any():  # too few documents, or a control that never varies
        return None
    fit = sm.OLS(d[y], sm.add_constant(d[xs])).fit(cov_type="HC1")
    x = xs[0]
    return {"n": len(d), "beta_bp_per_sd": fit.params[x], "t": fit.tvalues[x], "p": fit.pvalues[x], "r2": fit.rsquared}


def bh_qvalues(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values (q-values); missing p-values stay missing."""
    valid = p.astype(float).dropna().sort_values()
    ranked = valid * len(valid) / np.arange(1, len(valid) + 1)
    q = ranked[::-1].cummin()[::-1].clip(upper=1.0)
    return q.reindex(p.index)


def regress(panel: pd.DataFrame, methods: list[str], groups: list[str] = GROUPS) -> pd.DataFrame:
    splits = settings()["splits"]
    rows = []
    for g in groups:
        sub = panel[panel["group"] == g]
        if sub.empty:
            continue
        for method in methods:
            for variant in ("", "__shift"):
                x = f"{method}{variant}"
                if x not in sub or (variant and method.startswith("llmshift:")):
                    continue  # the change in Claude's comparison score is a second difference with no meaning
                key = {"doc_type": g, "method": method, "regressor": "shift" if variant else "level"}
                for y in MAIN + DIAGNOSTIC:
                    r = _fit(sub, y, [x])
                    if r:
                        rows.append({**key, "outcome": y, "sample": "all", "control": "none", **r})
                for y in ROBUST:
                    r = _fit(sub, y, [x, "d3m"])
                    if r:
                        rows.append({**key, "outcome": y, "sample": "all", "control": "d3m", **r})
                    if g in ("statement", "presser"):
                        r = _fit(sub, y, [x, "change_bp"])
                        if r:
                            rows.append({**key, "outcome": y, "sample": "all", "control": "decision", **r})
                    if g == "statement":
                        r = _fit(sub[sub["presser_meeting"] == False], y, [x])  # noqa: E712 (NaN-safe)
                        if r:
                            rows.append({**key, "outcome": y, "sample": "no_presser", "control": "none", **r})
                        if f"{x}__presser" in sub:
                            r = _fit(sub, y, [x, f"{x}__presser"])
                            if r:
                                rows.append({**key, "outcome": y, "sample": "all", "control": "presser", **r})
                    base_x = f"{BASELINE}{variant}"
                    if method.startswith("llm:") and base_x in sub:
                        r = _fit(sub, y, [x, base_x])
                        if r:
                            rows.append({**key, "outcome": y, "sample": "all", "control": "baseline", **r})
                    for name in ("development", "holdout"):
                        lo, hi = splits[name]
                        part = sub[(sub["date"] >= lo) & (sub["date"] <= hi)]
                        r = _fit(part, y, [x])
                        if r:
                            rows.append({**key, "outcome": y, "sample": name, "control": "none", **r})
    res = pd.DataFrame(rows)
    if res.empty:
        return res
    main = (
        (res["sample"] == "all") & (res["control"] == "none") & res["outcome"].isin(MAIN) & res["doc_type"].isin(FAMILY)
    )
    res["q_bh"] = np.nan
    res.loc[main, "q_bh"] = bh_qvalues(res.loc[main, "p"])
    return res


def response_curves(
    events: pd.DataFrame,
    yields: pd.DataFrame,
    panel: pd.DataFrame,
    methods: list[str],
    groups: list[str] = GROUPS,
    pre: int = 5,
    post: int = 20,
) -> pd.DataFrame:
    """Average cumulative 2y move around releases, by tercile of tone.

    Day 0 is the close that ends the release window; values are relative to the
    close that opens it, so a one-day window has day -1 at zero.
    """
    ev = _windows(events, yields.index).set_index("doc_id")
    y = yields["2 Yr"].to_numpy()
    offsets = np.arange(-pre, post + 1)
    rows = []
    for g in groups:
        sub = panel[panel["group"] == g]
        for method in methods:
            for variant in ("", "__shift"):
                x = f"{method}{variant}"
                if x not in sub:
                    continue
                d = sub[["doc_id", x]].dropna()
                if len(d) < 30:
                    continue
                # ranks, not values: Claude's shift scores are a few integers, so value cut points would repeat
                d = d.assign(bucket=pd.qcut(d[x].rank(method="first"), 3, labels=["dovish", "middle", "hawkish"]))
                for bucket, grp in d.groupby("bucket", observed=True):
                    paths = []
                    for doc in grp["doc_id"]:
                        if doc not in ev.index:
                            continue
                        i0, i1 = int(ev.at[doc, "i0"]), int(ev.at[doc, "i1"])
                        idx = i1 + offsets
                        if idx.min() < 0 or idx.max() >= len(y):
                            continue
                        paths.append(100 * (y[idx] - y[i0]))
                    if len(paths) < 5:
                        continue
                    arr = np.vstack(paths)
                    mean, se = np.nanmean(arr, 0), np.nanstd(arr, 0, ddof=1) / np.sqrt(len(arr))
                    for k, off in enumerate(offsets):
                        rows.append(
                            {
                                "doc_type": g,
                                "method": method,
                                "regressor": "shift" if variant else "level",
                                "bucket": str(bucket),
                                "day": int(off),
                                "mean_bp": float(mean[k]),
                                "se_bp": float(se[k]),
                                "n": len(arr),
                            }
                        )
    return pd.DataFrame(rows)
