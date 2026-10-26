"""Look-ahead through the weights: does the scorer recognise documents it has read?

The model was trained on text that includes every past FOMC document and the
market reaction to it. Three checks, carried over from the HW2 GameStop audit:

1. Identification: mask dates, names and rate levels, then ask the model when
   the document was issued. High accuracy means recognition is possible.
2. Invariance: score masked and unmasked versions of the same documents. If
   the scores agree, the score does not depend on recognising the document.
3. Clean sample: documents released after the model's knowledge cutoff cannot
   be remembered; results there are the uncontaminated benchmark.

Identification can also come from legitimate content (a document about the
pandemic is from 2020), so (1) bounds the risk; (2) and (3) carry the weight.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from .config import DATA, INTERIM, LLM_DIR
from .llm.scorer import Job, load_records

MONTH = (
    r"(?:January|February|March|April|June|July|August|September|October|November|December|"
    r"Jan\.|Feb\.|Mar\.|Apr\.|Aug\.|Sept\.|Oct\.|Nov\.|Dec\.)"
)
MONTH_OR_MAY = MONTH[:-1] + r"|May)"
YEAR = r"(?:19[5-9]\d|20\d{2})"

_RULES = [
    (re.compile(rf"\b{MONTH_OR_MAY}\s+\d{{1,2}}(?:\s*[-–]\s*(?:{MONTH_OR_MAY}\s+)?\d{{1,2}})?,?\s+{YEAR}\b"), "[DATE]"),
    (re.compile(rf"\b{MONTH_OR_MAY}\s+{YEAR}\b"), "[DATE]"),
    (re.compile(rf"\b{YEAR}s?\b"), "[YEAR]"),
    (re.compile(rf"\b{MONTH}\b"), "[MONTH]"),
    (re.compile(r"\b\d+(?:-\d/\d|\.\d+|/\d)?\s*(?:to|-)\s*\d+(?:-\d/\d|\.\d+|/\d)?\s+percent"), "[RANGE] percent"),
    (
        re.compile(
            r"\b(Chair(?:man|woman)?|Vice Chair(?:man)?|Governor|President|Secretary|Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?"
        ),
        r"\1 [NAME]",
    ),
    (re.compile(r"\b(CHAIR(?:MAN)?)\s+[A-Z][A-Z'\-]+\."), r"\1 [NAME]."),
    (re.compile(r"(?m)^(?!CHAIR)[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)+\.(?= )"), "[REPORTER]."),
    (re.compile(r"\b[A-Z][a-z]+(?: [A-Z]\.)+ [A-Z][a-z]+(?:-[A-Z][a-z]+)?(?:,? Jr\.)?"), "[NAME]"),
]


def anonymize(text: str) -> str:
    for rx, repl in _RULES:
        text = rx.sub(repl, text)
    return text


IDENTIFY_SYSTEM = """\
You are helping audit a research pipeline for memorization. You will see a Federal Reserve document with dates, names and rate levels masked. Estimate when it was released, as precisely as the text allows, and list the textual cues you relied on. Guess even when unsure, and say how confident you are."""

IDENTIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "year": {"type": "integer"},
        "month": {"type": "integer", "enum": list(range(1, 13))},
        "confidence": {"type": "number"},
        "cues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["year", "month", "confidence", "cues"],
    "additionalProperties": False,
}


def identify_jobs(docs: pd.DataFrame) -> list[Job]:
    from .llm.rubric import DOC_LABELS

    jobs = []
    for d in docs.itertuples():
        text = anonymize((INTERIM / "texts" / f"{d.doc_id}.txt").read_text())
        jobs.append(
            Job(
                "identify",
                d.doc_id,
                IDENTIFY_SYSTEM,
                f"Document type: {DOC_LABELS[d.doc_type]}\n\n<document>\n{text}\n</document>",
                IDENTIFY_SCHEMA,
                {"doc_id": d.doc_id, "release_date": d.release_date},
            )
        )
    return jobs


def identification_report(model: str) -> pd.DataFrame:
    rows = []
    for r in load_records(model, "identify"):
        if r["status"] != "ok":
            continue
        true = pd.Timestamp(r["meta"]["release_date"])
        p = r["parsed"]
        err = abs((p["year"] - true.year) * 12 + (p["month"] - true.month))
        rows.append(
            {
                "doc_id": r["key"],
                "doc_type": r["key"].split("_")[0],
                "true": true.strftime("%Y-%m"),
                "guess": f"{p['year']}-{p['month']:02d}",
                "abs_error_months": err,
                "exact_month": err == 0,
                "same_year": p["year"] == true.year,
                "confidence": p["confidence"],
            }
        )
    return pd.DataFrame(rows)


def stability_report(model: str, tag: str = "r2") -> pd.DataFrame:
    """Test-retest: the same documents scored again in a separate batch (`fomc llm-submit --run-tag r2`)."""
    from .llm.scorer import level_scores

    first, again = level_scores(model, "level"), level_scores(model, f"level_{tag}")
    both = first.merge(again, on="doc_id", suffixes=("_1", "_2")) if len(again) else pd.DataFrame()
    if both.empty:
        return pd.DataFrame()
    step = (both["overall_stance_1"] - both["overall_stance_2"]).abs()
    return pd.DataFrame(
        [
            {
                "run_tag": tag,
                "n": len(both),
                "corr_stance_score": both["score_1"].corr(both["score_2"]),
                "mean_abs_diff": (both["score_1"] - both["score_2"]).abs().mean(),
                "overall_stance_agreement": (step == 0).mean(),
                "within_one_step": (step <= 1).mean(),
            }
        ]
    )


def invariance_report(model: str) -> pd.DataFrame:
    """Masked versus unmasked scores for the same documents."""
    from .llm.scorer import level_scores

    raw, anon = level_scores(model, "level"), level_scores(model, "level_anon")
    both = raw.merge(anon, on="doc_id", suffixes=("_raw", "_anon"))
    if both.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "n": len(both),
                "corr_stance_score": both["score_raw"].corr(both["score_anon"]),
                "mean_abs_diff": (both["score_raw"] - both["score_anon"]).abs().mean(),
                "overall_stance_agreement": (both["overall_stance_raw"] == both["overall_stance_anon"]).mean(),
            }
        ]
    )


# ---------------------------------------------------------------- scorer drift
# A long-running index is only comparable over time if the reader does not change. Every month the same eight
# documents are scored again through today's pipeline and model (`fomc drift`, about $0.30): a silent model update, a
# change in how the Fed's pages are cleaned or a prompt edit shows up as a gap between the new reading and the first.
ANCHORS = DATA / "drift" / "anchors.json"  # chosen once from the test-retest set, then fixed (committed)
DRIFT_LIMITS = {"mean_abs_diff": 0.10, "overall_stance_agreement": 0.75}  # beyond either: the reader has moved


def anchors(model: str) -> list[str]:
    """The eight anchor documents, two per type: read from data/drift/anchors.json, or chosen now (once) from the
    documents scored twice for the test-retest check, at the first and third quartile of each type's ids."""
    if ANCHORS.exists():
        return json.loads(ANCHORS.read_text())["doc_ids"]
    from .llm.scorer import level_scores

    retest = sorted(level_scores(model, "level_r2")["doc_id"])
    picks = []
    for t in ("statement", "minutes", "presser", "speech"):
        ids = [d for d in retest if d.startswith(t + "_")]
        if ids:
            picks += dict.fromkeys([ids[len(ids) // 4], ids[3 * len(ids) // 4]])  # one, if the type has only one
    ANCHORS.parent.mkdir(parents=True, exist_ok=True)
    ANCHORS.write_text(json.dumps({"chosen_from": "level_r2", "doc_ids": picks}, indent=1) + "\n")
    return picks


def drift_tag(month: str) -> str:
    """The run tag of a month's re-reading: '2026-11' -> 'd202611'."""
    return "d" + month.replace("-", "")


def drift_report(model: str) -> dict:
    """Each month's re-reading of the anchors against their first reading (empty before the anchors exist)."""
    from .llm import rubric
    from .llm.scorer import level_scores

    if not ANCHORS.exists():
        return {}
    ids = set(anchors(model))
    first = level_scores(model, "level")
    first = first[first["doc_id"].isin(ids)]
    months = []
    for p in sorted((LLM_DIR / model / rubric.RUBRIC_VERSION).glob("level_d[0-9]*")):
        again = level_scores(model, p.name)
        both = first.merge(again[again["doc_id"].isin(ids)], on="doc_id", suffixes=("_1", "_2"))
        if both.empty:
            continue
        gap = (both["score_1"] - both["score_2"]).abs()
        same = float(((both["overall_stance_1"] - both["overall_stance_2"]).abs() == 0).mean())
        tag = p.name.removeprefix("level_d")
        months.append(
            {
                "month": f"{tag[:4]}-{tag[4:6]}",
                "n": len(both),
                "mean_abs_diff": round(float(gap.mean()), 4),
                "max_abs_diff": round(float(gap.max()), 4),
                "overall_stance_agreement": round(same, 4),
                "drifted": bool(
                    gap.mean() > DRIFT_LIMITS["mean_abs_diff"] or same < DRIFT_LIMITS["overall_stance_agreement"]
                ),
            }
        )
    return {"anchors": sorted(ids), "limits": DRIFT_LIMITS, "months": months}
