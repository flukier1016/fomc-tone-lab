"""The policy decision in each FOMC statement, and how the wording changed.

Target range: the "X to Y percent" quoted next to "target range" in the
statement ("...to 5-1/4 to 5-1/2 percent", "the current 0 to 1/4 percent
target range"). Action: the change in the upper bound against the previous
statement, which is robust to the many ways the decision has been phrased
since 2009; the wording is only used for the first statement in the sample.

Wording: a word-level diff against the previous statement, the way desks
read a new statement next to the old one.
"""

from __future__ import annotations

import difflib
import re

import pandas as pd

_NUM = r"(\d+-\d/\d|\d/\d|\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"{_NUM}\s*to\s*{_NUM}\s*percent\b(?!age)", re.I)
_HIKE = re.compile(r"decided(?: today)? to (?:raise|increase)\b", re.I)
_CUT = re.compile(r"decided(?: today)? to (?:lower|reduce|cut)\b", re.I)
_HOLD = re.compile(
    r"(?:decided(?: today)? to|will) (?:maintain|keep|leave)\b|reaffirmed its view that the current", re.I
)
_SENTENCE = re.compile(r"[^.]*target range[^.]*\.", re.I)
_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-"})


def _value(token: str) -> float:
    """'5-1/4' -> 5.25, '1/4' -> 0.25, '0' -> 0.0, '4.75' -> 4.75."""
    if "/" in token:
        whole, _, frac = token.rpartition("-")
        num, den = frac.split("/")
        return (int(whole) if whole else 0) + int(num) / int(den)
    return float(token)


def parse_statement(text: str) -> dict:
    """Target range and the action as worded; `action` is +1 hike, -1 cut, 0 hold, None if unstated."""
    text = (text or "").translate(_DASHES)  # the Board's pages use non-breaking hyphens in "1\u20111/4"
    low = high = None
    for sentence in _SENTENCE.findall(text):
        if "directs the Desk" in sentence:  # a quoted directive in an implementation notice, not a decision
            continue
        m = _RANGE.search(sentence)
        if m:
            low, high = _value(m.group(1)), _value(m.group(2))
            break
    action = 1 if _HIKE.search(text) else -1 if _CUT.search(text) else 0 if _HOLD.search(text) else None
    return {"action": action, "range_low": low, "range_high": high}


_TOKEN = re.compile(r"\n\s*\n|\S+")
PARA = "\n\n"


def words(text: str) -> list[str]:
    """Word tokens, with paragraph breaks kept as their own token so a redline keeps its paragraphs."""
    return [PARA if t.isspace() else t for t in _TOKEN.findall(text or "")]


def _count(tokens: list[str]) -> int:
    return sum(t != PARA for t in tokens)


def _join(tokens: list[str]) -> str:
    return re.sub(r" ?\n\n ?", PARA, " ".join(tokens))


def diff(old: str, new: str) -> tuple[list[dict], dict]:
    """Word-level redline of `new` against `old`: segments of equal, insert and delete text, and counts."""
    a, b = words(old), words(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    segments, added, removed = [], 0, 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            segments.append({"op": "equal", "text": _join(b[j1:j2])})
            continue
        if op in ("delete", "replace"):
            segments.append({"op": "delete", "text": _join(a[i1:i2])})
            removed += _count(a[i1:i2])
        if op in ("insert", "replace"):
            segments.append({"op": "insert", "text": _join(b[j1:j2])})
            added += _count(b[j1:j2])
    return segments, {"similarity": sm.ratio(), "words_added": added, "words_removed": removed}


def decisions(statements: pd.DataFrame) -> pd.DataFrame:
    """One row per statement: target range, action, change in bp, and how much the wording changed.

    `statements` needs doc_id, meeting_date, release_date and text. A statement that quotes no
    target range (swap lines, framework reviews, balance-sheet notices) is kept with action None
    and stays out of the chain: each decision is compared with the previous decision.
    """
    rows, prev_high, prev_text, prev_id = [], None, None, None
    for s in statements.sort_values(["release_date", "doc_id"]).itertuples():
        p = parse_statement(s.text)
        decision = p["range_high"] is not None
        action, change = (p["action"] if decision else None), None
        if decision and prev_high is not None:
            change = round(100 * (p["range_high"] - prev_high))
            action = (change > 0) - (change < 0)
        row = {
            "doc_id": s.doc_id,
            "meeting_date": s.meeting_date,
            "release_date": s.release_date,
            "action": action,
            "change_bp": change,
            "range_low": p["range_low"],
            "range_high": p["range_high"],
            "prev_doc_id": prev_id,
            "similarity": None,
            "words_added": None,
            "words_removed": None,
            "n_words": _count(words(s.text)),
        }
        if decision and prev_text is not None:
            _, stats = diff(prev_text, s.text)
            row.update(stats)
        else:
            row["prev_doc_id"] = None
        rows.append(row)
        if decision:
            prev_high, prev_text, prev_id = p["range_high"], s.text, s.doc_id
    return pd.DataFrame(rows)


def action_label(action) -> str:
    return {1: "hike", -1: "cut", 0: "hold"}.get(action, "n/a")
