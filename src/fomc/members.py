"""One member of the Committee over time: the titles held, the dissents, and where the tone of the speeches shifted.

The tone line is the member's own speeches scored by the default reader, low-relevance ones left out as the research
does. A shift is a change point of that line, found by circular binary segmentation (Olshen et al. 2004): in a
stretch of speeches, in date order, find the run that differs most from the rest of the stretch (a run at either end
is an ordinary split), keep it when fewer than 1 in 100 shuffles of the same speeches show as large a difference, and
search each new stretch again. Each stretch keeps at least five speeches. On shuffled speeches, where nothing
changed, the rule finds a shift about once in a hundred members.
"""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

MIN_SPEECHES = 5  # in every stretch
SHUFFLES = 499
ALPHA = 0.01
MAX_REGIMES = 5
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b({_MONTHS}) (\d{{1,2}}), (\d{{4}})")


def took_office(sentence: str | None) -> str | None:
    """The first date in the Fed's "took office" sentence, as YYYY-MM-DD."""
    m = _DATE.search(sentence or "")
    if not m:
        return None
    month = _MONTHS.split("|").index(m.group(1)) + 1
    return date(int(m.group(3)), month, int(m.group(2))).isoformat()


def office(sentence: str | None) -> str | None:
    """What a "took office" sentence is about: joining the Board, or a title."""
    s = sentence or ""
    if "member of the Board" in s:
        return "Board member"
    m = re.search(r"\b(?:as|is) (?:the )?(?:\w+ )??(Vice Chair for Supervision|Vice Chair|[Cc]hairman|Chair)\b", s)
    if m:
        return "Chair" if m.group(1).lower() == "chairman" else m.group(1)
    for title in ("First Vice President", "interim president", "president"):
        if re.search(rf"\b{title}\b", s, re.I):
            return title[0].upper() + title[1:]
    return None


def offices(bio: dict | None) -> list[dict]:
    """The dated offices in the biography (joining the Board, a later title), oldest first."""
    out = []
    for key in ("took", "role"):
        when = took_office((bio or {}).get(key))
        if when:
            out.append({"date": when, "office": office(bio[key])})
    return sorted(out, key=lambda o: o["date"])


def role_spells(speeches: pd.DataFrame) -> list[dict]:
    """Consecutive runs of the title the member spoke under (Governor, then Chair, then Governor again).
    `speeches`: date, role, in date order."""
    out: list[dict] = []
    for r in speeches.itertuples():
        if not isinstance(r.role, str) or not r.role:
            continue
        if out and out[-1]["role"] == r.role:
            out[-1].update(to=r.date, n=out[-1]["n"] + 1)
        else:
            out.append({"role": r.role, "from": r.date, "to": r.date, "n": 1})
    return out


def _runs(n: int) -> np.ndarray:
    """Which runs [i, j) of n speeches may be tested: the run and the rest both hold MIN_SPEECHES, and so does each
    piece of the rest."""
    i, j = np.arange(n + 1)[:, None], np.arange(n + 1)[None, :]
    k = j - i
    return (
        (k >= MIN_SPEECHES)
        & (n - k >= MIN_SPEECHES)
        & ((i == 0) | (i >= MIN_SPEECHES))
        & ((j == n) | (n - j >= MIN_SPEECHES))
    )


def _gap(x: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """For every run [i, j): the difference between its mean and the rest's, in units of the standard error it would
    have if the stretch's spread were the same everywhere (the spread itself does not change under a shuffle)."""
    n = len(x)
    s = np.concatenate([[0.0], np.cumsum(x)])
    inside = s[None, :] - s[:, None]
    k = (np.arange(n + 1)[None, :] - np.arange(n + 1)[:, None]).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap = np.abs(inside / k - (s[-1] - inside) / (n - k)) / np.sqrt(1 / k + 1 / (n - k))
    gap[~ok] = -1.0
    return gap


def _shift(x: np.ndarray) -> tuple[float, int, int] | None:
    """The run that differs most from the rest of the stretch, with its permutation p-value, or None."""
    ok = _runs(len(x))
    if not ok.any():
        return None
    gap = _gap(x, ok)
    i, j = np.unravel_index(np.argmax(gap), gap.shape)
    rng = np.random.default_rng(0)  # the same answer on every request
    null = np.array([_gap(rng.permutation(x), ok).max() for _ in range(SHUFFLES)])
    p = (1 + int((null >= gap[i, j] - 1e-12).sum())) / (SHUFFLES + 1)
    return (p, int(i), int(j)) if p < ALPHA else None


def regimes(dates: list[str], scores: list[float]) -> list[dict]:
    """Stretches of steady tone: from, to, n and the mean score of each, oldest first."""
    x = np.asarray(scores, dtype=float)
    if not len(x):
        return []
    cuts, settled = [0, len(x)], set()
    while len(cuts) - 1 < MAX_REGIMES:
        found = []
        for lo, hi in zip(cuts, cuts[1:]):
            if (lo, hi) in settled:
                continue
            hit = _shift(x[lo:hi])
            if hit is None:
                settled.add((lo, hi))
            else:
                found.append((hit[0], lo + hit[1], lo + hit[2], lo, hi))
        if not found:
            break
        p, i, j, lo, hi = min(found)  # the clearest shift first
        cuts = sorted({*cuts, i, j})
    return [
        {"from": dates[lo], "to": dates[hi - 1], "n": hi - lo, "mean": float(x[lo:hi].mean())}
        for lo, hi in zip(cuts, cuts[1:])
    ]


def lean(preferred: str, action: int | None, reason: str = "") -> int:
    """+1 when a dissent wanted tighter policy than the decision, -1 looser, 0 when neither: no change is hawkish
    against a cut and dovish against a hike; objecting to an easing bias in the statement is hawkish."""
    if preferred in ("hike", "cut"):
        return 1 if preferred == "hike" else -1
    if preferred == "hold":
        return -int(np.sign(action)) if action else 0
    said = (reason or "").lower()
    return 1 if "easing bias" in said else -1 if "tightening bias" in said else 0


WANTED = {"hike": "wanted a hike", "cut": "wanted a cut", "hold": "wanted no change"}


def dissent_label(preferred: str, reason: str = "") -> str:
    """What a dissent wanted, in a few words."""
    if preferred in WANTED:
        return WANTED[preferred]
    said = (reason or "").lower()
    if "easing bias" in said:
        return "against an easing bias"
    if "tightening bias" in said:
        return "against a tightening bias"
    if "securities" in said or "balance sheet" in said:
        return "on the balance sheet"
    return "not on the rate"


def events(
    speeches: pd.DataFrame,
    spells: list[dict],
    stretches: list[dict],
    dissents: pd.DataFrame,
    dated: list[dict],
    actions: dict[str, int] | None = None,
) -> list[dict]:
    """What changed, newest first: the offices the Fed's biography dates (`dated`, from `offices`), the first speech
    under each new title the biography does not already date, every dissent, each shift in tone, and the most hawkish
    and most dovish speech. `actions`: the decision of each statement (+1 hike, 0 hold, -1 cut), so that a dissent
    for no change reads hawkish against a cut and dovish against a hike."""
    actions = actions or {}
    out = []
    for o in dated:
        text = "Joined the Board" if o["office"] == "Board member" else f"Took office as {o['office'] or 'member'}"
        out.append({"date": o["date"], "kind": "office", "office": o["office"], "text": f"{text} (Fed biography)"})

    def dated_already(role: str, when: str) -> bool:
        same = [o for o in dated if (o["office"] or "").lower() == role.lower()]
        return any(abs((date.fromisoformat(o["date"]) - date.fromisoformat(when)).days) <= 120 for o in same)

    for prev, cur in zip(spells, spells[1:]):
        if not dated_already(cur["role"], cur["from"]):
            out.append(
                {
                    "date": cur["from"],
                    "kind": "role",
                    "office": cur["role"],
                    "text": f"First speech as {cur['role']} (was {prev['role']})",
                }
            )
    for d in dissents.itertuples():
        out.append(
            {
                "date": d.date,
                "kind": "dissent",
                "direction": lean(d.preferred, actions.get(d.doc_id), d.reason),
                "text": f"Dissented: {dissent_label(d.preferred, d.reason)}",
                "detail": f"In the statement's words, {d.name.split()[-1]} {d.reason}.",
                "doc_id": d.doc_id,
                "preferred": d.preferred,
            }
        )
    for prev, cur in zip(stretches, stretches[1:]):
        way = "more hawkish" if cur["mean"] > prev["mean"] else "more dovish"
        out.append(
            {
                "date": cur["from"],
                "kind": "shift",
                "direction": 1 if cur["mean"] > prev["mean"] else -1,
                "text": f"Tone turned {way}: average {prev['mean']:+.2f} over {prev['n']} speeches, "
                f"then {cur['mean']:+.2f} over {cur['n']}",
            }
        )
    scored = speeches.dropna(subset=["score"])
    scored = scored[scored["relevance"] != "low"]
    if len(scored) >= MIN_SPEECHES:
        for kind, row in (
            ("hawkish", scored.loc[scored["score"].idxmax()]),
            ("dovish", scored.loc[scored["score"].idxmin()]),
        ):
            out.append(
                {
                    "date": row["date"],
                    "kind": "extreme",
                    "direction": 1 if kind == "hawkish" else -1,
                    "text": f"Most {kind} speech ({row['score']:+.2f}): {row['title']}",
                    "doc_id": row["doc_id"],
                }
            )
    return sorted(out, key=lambda e: e["date"], reverse=True)
