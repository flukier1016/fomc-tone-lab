"""Sentence splitting tuned for Fed prose (U.S., p.m., Mr., 1/4 percent, ...)."""

from __future__ import annotations

import re

_ABBREV = [
    "U.S.",
    "U.K.",
    "Mr.",
    "Ms.",
    "Mrs.",
    "Dr.",
    "Jr.",
    "St.",
    "No.",
    "Inc.",
    "Co.",
    "Corp.",
    "p.m.",
    "a.m.",
    "e.g.",
    "i.e.",
    "vs.",
    "etc.",
    "Jan.",
    "Feb.",
    "Mar.",
    "Apr.",
    "Aug.",
    "Sept.",
    "Sep.",
    "Oct.",
    "Nov.",
    "Dec.",
    "Gov.",
    "Fig.",
    "approx.",
]
_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z“\"(])")


def sentences(text: str, min_words: int = 4) -> list[str]:
    protected = text
    for i, abbr in enumerate(_ABBREV):
        protected = protected.replace(abbr, abbr.replace(".", f"\x00{i}\x00"))
    out = []
    for para in protected.split("\n"):
        for sent in _SPLIT.split(para):
            for i, abbr in enumerate(_ABBREV):
                sent = sent.replace(abbr.replace(".", f"\x00{i}\x00"), abbr)
            sent = " ".join(sent.split())
            if len(sent.split()) >= min_words:
                out.append(sent)
    return out
