"""Does Fed language say more about the next decision than the market already prices? (exploratory)

For every decision since 2009 (cut, hold or hike: -1, 0, +1) the inputs are only what was public before the
statement: the market's lean at the last close before the decision day (3-month bill and 2-year yields minus the
midpoint of the target range), the tone of the latest minutes, the mean tone of policy speeches in the 60 days
before, and the tone of the previous statement (Claude's level scores). A linear model of the decision is fit with
the market alone and with the market plus tone: the in-sample F-test (HC1) asks whether tone adds anything, and an
expanding-window forecast from 2017 asks whether it would have helped in real time, meeting by meeting. This test
was added after the results and is not part of the pre-registered ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .. import db, store

MARKET = ["lean_3m", "lean_2y"]  # basis points over the midpoint of the target range in force
TONE = ["minutes", "speeches", "statement"]  # Claude's level score, standardized in the regression
NAMES = {
    "lean_3m": "3-month bill over the policy rate",
    "lean_2y": "2-year over the policy rate",
    "minutes": "Tone of the latest minutes",
    "speeches": "Tone of speeches, last 60 days",
    "statement": "Tone of the previous statement",
}
OOS_START = "2017-01-01"  # the first expanding-window forecast; earlier years leave too few moves to learn from
SPEECH_DAYS = 60


def build_panel(con, method: str) -> pd.DataFrame:
    """One row per decision with only information public before it (each input strictly before the decision day)."""
    dec = db.query(
        con,
        "SELECT c.doc_id, c.release_date AS date, c.action, c.change_bp, c.range_low, c.range_high "
        "FROM decisions c WHERE c.action IS NOT NULL ORDER BY c.release_date",
    )
    dec["mid_before"] = (dec["range_low"] + dec["range_high"]) / 2 - dec["change_bp"].fillna(0) / 100
    yields = db.query(con, "SELECT date, t3m, t2y FROM yields WHERE t3m IS NOT NULL AND t2y IS NOT NULL ORDER BY date")
    docs = db.query(con, "SELECT doc_id, doc_type, release_date FROM documents WHERE note IS NULL")
    sc = store.load_scores(con)[method].merge(docs, on="doc_id")  # policy speeches only (low relevance dropped)
    minutes = sc[sc.doc_type == "minutes"].sort_values("release_date")
    speeches = sc[sc.doc_type == "speech"].sort_values("release_date")
    statements = dict(zip(sc[sc.doc_type == "statement"]["doc_id"], sc[sc.doc_type == "statement"]["score"]))
    rows, prev = [], None
    for d in dec.itertuples():
        y = yields[yields.date < d.date].tail(1)
        m = minutes[minutes.release_date < d.date].tail(1)
        window = pd.Timestamp(d.date) - pd.Timedelta(days=SPEECH_DAYS)
        s = speeches[(speeches.release_date < d.date) & (pd.to_datetime(speeches.release_date) >= window)]
        rows.append(
            {
                "doc_id": d.doc_id,
                "date": d.date,
                "action": int(d.action),
                "lean_3m": (float(y.t3m.iloc[0]) - d.mid_before) * 100 if len(y) else np.nan,
                "lean_2y": (float(y.t2y.iloc[0]) - d.mid_before) * 100 if len(y) else np.nan,
                "minutes": float(m.score.iloc[0]) if len(m) else np.nan,
                "speeches": float(s.score.mean()) if len(s) else np.nan,
                "statement": statements.get(prev, np.nan) if prev else np.nan,
            }
        )
        prev = d.doc_id
    panel = pd.DataFrame(rows)
    panel["speeches"] = panel["speeches"].ffill()  # a quiet stretch keeps the last reading
    return panel.dropna().reset_index(drop=True)


def _fit(panel: pd.DataFrame, cols: list[str]):
    X = sm.add_constant(panel[cols], has_constant="add")
    return sm.OLS(panel["action"].astype(float), X).fit(cov_type="HC1")


def run(con, method: str, seed: int = 7) -> dict:
    panel = build_panel(con, method)
    z = panel.copy()
    for c in MARKET + TONE:  # per standard deviation, for the coefficients only (predictions do not depend on it)
        z[c] = (z[c] - z[c].mean()) / z[c].std()
    market, both = _fit(z, MARKET), _fit(z, MARKET + TONE)
    ftest = both.f_test(" = 0, ".join(TONE) + " = 0")
    coefs = [
        {
            "term": c,
            "name": NAMES[c],
            "beta": float(both.params[c]),
            "t": float(both.tvalues[c]),
            "p": float(both.pvalues[c]),
        }
        for c in MARKET + TONE
    ]
    # expanding window: each forecast uses only the decisions before it
    test = panel.index[panel.date >= OOS_START]
    preds = []
    for i in test:
        train = panel.iloc[:i]
        row = panel.iloc[[i]]
        f = {name: _fit(train, cols) for name, cols in (("market", MARKET), ("both", MARKET + TONE))}
        pm = float(f["market"].predict(sm.add_constant(row[MARKET], has_constant="add")).iloc[0])
        pb = float(f["both"].predict(sm.add_constant(row[MARKET + TONE], has_constant="add")).iloc[0])
        preds.append({"date": row.date.iloc[0], "action": int(row.action.iloc[0]), "market": pm, "both": pb})
    oos = pd.DataFrame(preds)
    err_m, err_b = (oos.action - oos.market) ** 2, (oos.action - oos.both) ** 2
    diff = (err_b - err_m).to_numpy()  # negative: tone helped
    boot = np.random.default_rng(seed).choice(diff, (5000, len(diff))).mean(axis=1)

    def hits(col: str) -> float:  # the right call when the forecast is rounded to cut, hold or hike
        return float((np.clip(np.round(oos[col]), -1, 1) == oos.action).mean())

    return {
        "method": method,
        "n": len(panel),
        "first": panel.date.iloc[0],
        "last": panel.date.iloc[-1],
        "moves": {"hikes": int((panel.action == 1).sum()), "cuts": int((panel.action == -1).sum())},
        "in_sample": {
            "r2_market": float(market.rsquared),
            "r2_both": float(both.rsquared),
            "f": float(np.squeeze(ftest.fvalue)),
            "p": float(ftest.pvalue),
            "coefs": coefs,
        },
        "out_of_sample": {
            "start": oos.date.iloc[0],
            "n": len(oos),
            "moves": int((oos.action != 0).sum()),
            "mse_market": float(err_m.mean()),
            "mse_both": float(err_b.mean()),
            "diff": float(diff.mean()),
            "ci_low": float(np.percentile(boot, 2.5)),
            "ci_high": float(np.percentile(boot, 97.5)),
            "p_boot": float(min(1.0, 2 * min(np.mean(boot <= 0), np.mean(boot >= 0)))),
            "hit_market": hits("market"),
            "hit_both": hits("both"),
        },
        "meetings": oos.round(4).to_dict("records"),
    }
