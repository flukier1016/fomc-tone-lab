"""Figures for the write-up (static PNG, light surface).

Style follows the dataviz method: one axis per panel (the tone index and the
2-year yield are stacked panels, never a dual axis), categorical colors in a
fixed order (validated: first three slots pass all-pairs CVD checks), 2px
lines, recessive grid, direct labels beside lines.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import RESULTS

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # fixed order: blue, orange, aqua
BAND = "#e1e0d9"
DOC_TITLES = {
    "statement": "Statements",
    "minutes": "Minutes",
    "presser": "Press conferences",
    "speech": "Board speeches",
}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK2, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)


def _figure(nrows: int, height: float, sharex: bool = True):
    fig, axes = plt.subplots(nrows, 1, figsize=(9, height), sharex=sharex, facecolor=SURFACE)
    return fig, np.atleast_1d(axes)


def tone_index(scores: pd.DataFrame, docs: pd.DataFrame, yields: pd.DataFrame, method: str) -> str:
    df = docs[["doc_id", "doc_type", "release_date"]].merge(scores[["doc_id", "score"]], on="doc_id")
    df["date"] = pd.to_datetime(df["release_date"])
    types = [t for t in DOC_TITLES if t in set(df["doc_type"])]
    fig, axes = _figure(len(types) + 1, 1.7 * (len(types) + 1))
    for ax, t in zip(axes, types):
        sub = df[df["doc_type"] == t].sort_values("date")
        ax.scatter(sub["date"], sub["score"], s=9, color=MUTED, alpha=0.5, linewidths=0)
        window = 25 if t == "speech" else 5
        ax.plot(sub["date"], sub["score"].rolling(window, min_periods=2).median(), color=SERIES[0], lw=2)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_title(f"{DOC_TITLES[t]}: tone ({method}), rolling median", loc="left", fontsize=10, color=INK)
        _style(ax)
    ax = axes[-1]
    y2 = yields["2 Yr"].loc[df["date"].min() :]
    ax.plot(y2.index, y2, color=INK2, lw=1.5)
    ax.set_title("2-year Treasury par yield, percent", loc="left", fontsize=10, color=INK)
    _style(ax)
    fig.tight_layout()
    path = RESULTS / f"fig_tone_index_{method.replace(':', '_')}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)


def event_coefficients(results: pd.DataFrame, outcome: str = "d2y") -> str:
    res = results[results["outcome"] == outcome].copy()
    res["se"] = res["beta_bp_per_sd"] / res["t"]
    methods = list(dict.fromkeys(res["method"]))[:3]
    types = [t for t in DOC_TITLES if t in set(res["doc_type"])]
    fig, axes = plt.subplots(1, 2, figsize=(9, 0.9 + 0.75 * len(types)), sharey=True, facecolor=SURFACE)
    for ax, reg in zip(axes, ("level", "shift")):
        for k, m in enumerate(methods):
            sub = res[(res["method"] == m) & (res["regressor"] == reg)].set_index("doc_type")
            for i, t in enumerate(types):
                if t not in sub.index:
                    continue
                y = i + (k - (len(methods) - 1) / 2) * 0.22
                b, se = sub.loc[t, "beta_bp_per_sd"], sub.loc[t, "se"]
                ax.plot([b - 1.96 * se, b + 1.96 * se], [y, y], color=SERIES[k], lw=2, solid_capstyle="round")
                ax.plot(
                    b,
                    y,
                    "o",
                    ms=8,
                    color=SERIES[k],
                    markeredgecolor=SURFACE,
                    markeredgewidth=2,
                    label=m if i == 0 else None,
                )
        ax.axvline(0, color=MUTED, lw=0.8)
        ax.set_yticks(range(len(types)), [DOC_TITLES[t] for t in types])
        ax.set_title(f"Tone {reg}: bp per 1 SD, 95% CI", loc="left", fontsize=10, color=INK)
        _style(ax)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    axes[0].invert_yaxis()
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(methods), frameon=False, fontsize=9)
    fig.suptitle(f"Change in 2-year yield over the release window ({outcome})", y=1.06, fontsize=11, color=INK)
    fig.tight_layout()
    path = RESULTS / f"fig_event_{outcome}.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def backtest_curves(
    curves: dict[str, pd.Series],
    placebo_paths: np.ndarray | None,
    index: pd.DatetimeIndex | None,
    title: str,
    name: str,
) -> str:
    fig, axes = _figure(1, 3.6)
    ax = axes[0]
    if placebo_paths is not None and len(placebo_paths):
        lo, hi = np.nanpercentile(placebo_paths, [5, 95], axis=0)
        ax.fill_between(index, lo, hi, color=BAND, alpha=0.8, linewidth=0, label="Shuffled scores, 5-95%")
    for k, (label, ret) in enumerate(list(curves.items())[:3]):
        cum = ret.cumsum() * 100
        ax.plot(cum.index, cum, color=SERIES[k], lw=2, label=label)
        ax.annotate(
            label,
            (cum.index[-1], cum.iloc[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            color=INK2,
            fontsize=8,
            va="center",
        )
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.set_ylabel("cumulative return, %", color=INK2, fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _style(ax)
    fig.tight_layout()
    path = RESULTS / f"fig_backtest_{name}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)
