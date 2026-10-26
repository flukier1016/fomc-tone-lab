"""Baseline 1: a transparent hawkish-dovish dictionary.

In the spirit of Apel and Grimaldi (2012): count economic nouns that sit near
a direction word, and sign each pair by what it implies for policy. Rising
inflation or strong activity is hawkish; rising unemployment is dovish;
explicit policy phrases count directly. This is our own implementation of the
idea, not a replication of their word list, and it ignores negation.
"""

from __future__ import annotations

import re

import pandas as pd

from .textutil import sentences

UP = (
    r"(?:high|higher|highest|rising|rise|rose|risen|increas\w*|elevated|strong|stronger|robust|"
    r"accelerat\w*|upward|firm|firmer|solid|tight|tighter|above|pick(?:ed)? up|persistent)"
)
DOWN = (
    r"(?:low|lower|lowest|falling|fall|fell|fallen|declin\w*|decreas\w*|subdued|weak|weaker|"
    r"weaken\w*|soft|softer|soften\w*|moderat\w*|slow\w*|downward|below|muted|eas(?:ed|ing))"
)
PRICES = r"(?:inflation|inflationary pressures?|price pressures?|prices|wages?|labor costs|unit labor costs)"
ACTIVITY = (
    r"(?:growth|economic activity|activity|demand|spending|employment|job gains|payrolls|"
    r"output|investment|consumption|economy|labor market)"
)
SLACK = r"(?:unemployment rate|unemployment|slack|resource slack)"
POLICY_HAWK = (
    r"(?:raise the target range|increase the target range|additional (?:policy )?firming|"
    r"further (?:policy )?firming|tighten\w*|remov\w* (?:of )?(?:policy )?accommodation|"
    r"reduc\w* (?:its|the) (?:securities )?holdings|balance sheet runoff|rate (?:increases|hikes))"
)
POLICY_DOVE = (
    r"(?:lower the target range|reduce the target range|rate cuts?|cut rates|"
    r"additional accommodation|highly accommodative|exceptionally low|increase (?:its|the) holdings|"
    r"asset purchases|be patient|lower for longer|easing of (?:monetary )?policy)"
)

GAP = r"(?:\W+\w+){0,5}?\W+"


def _pairs(noun: str, mod: str) -> re.Pattern:
    return re.compile(rf"\b{noun}\b{GAP}{mod}\b|\b{mod}\b{GAP}{noun}\b", re.I)


RULES = [
    (_pairs(PRICES, UP), +1),
    (_pairs(PRICES, DOWN), -1),
    (_pairs(ACTIVITY, UP), +1),
    (_pairs(ACTIVITY, DOWN), -1),
    (_pairs(SLACK, UP), -1),
    (_pairs(SLACK, DOWN), +1),
    (re.compile(rf"\b{POLICY_HAWK}\b", re.I), +1),
    (re.compile(rf"\b{POLICY_DOVE}\b", re.I), -1),
]


def spans(text: str) -> list[tuple[int, int, int]]:
    """Where the dictionary reads a direction in a text: (start, end, +1 hawkish or -1 dovish), in order."""
    return sorted((m.start(), m.end(), sign) for rx, sign in RULES for m in rx.finditer(text))


def sentence_counts(sentence: str) -> tuple[int, int]:
    hawk = dove = 0
    for rx, sign in RULES:
        n = len(rx.findall(sentence))
        if sign > 0:
            hawk += n
        else:
            dove += n
    return hawk, dove


def sentence_label(sentence: str) -> int:
    """0 dovish, 1 hawkish, 2 neutral (the Trillion Dollar Words coding)."""
    hawk, dove = sentence_counts(sentence)
    return 1 if hawk > dove else 0 if dove > hawk else 2


def document_score(text: str) -> dict:
    hawk = dove = 0
    for s in sentences(text):
        h, d = sentence_counts(s)
        hawk, dove = hawk + h, dove + d
    total = hawk + dove
    return {"score": (hawk - dove) / total if total else 0.0, "hawk_hits": hawk, "dove_hits": dove}


def score_documents(docs: pd.DataFrame, texts: dict[str, str]) -> pd.DataFrame:
    rows = [{"doc_id": d, **document_score(texts[d])} for d in docs["doc_id"]]
    return pd.DataFrame(rows)
