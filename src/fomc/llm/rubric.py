"""The scoring rubric, versioned.

Any edit to a prompt or schema below changes what the model is asked to do:
bump RUBRIC_VERSION so cached responses from the old wording are not mixed in.
docs/RUBRIC.md explains each choice.
"""

from __future__ import annotations

RUBRIC_VERSION = "v1"

DIMENSIONS = [
    "policy_action",
    "forward_guidance",
    "inflation_assessment",
    "activity_labor_assessment",
    "risk_balance",
    "balance_sheet",
]

DOC_LABELS = {
    "statement": "FOMC policy statement",
    "minutes": "Minutes of an FOMC meeting",
    "presser": "Transcript of the FOMC Chair's press conference",
    "speech": "Speech by a member of the Federal Reserve Board",
}

LEVEL_SYSTEM = """\
You score the monetary-policy stance of Federal Reserve communication for an academic study of how Fed language moves Treasury yields. Each request contains one document: an FOMC policy statement, FOMC minutes, a press conference transcript, or a speech by a member of the Board of Governors.

Score what the words say. The study tests whether text alone carries information, so knowledge of what happened later (subsequent decisions, data, market reactions) would contaminate the result. If you recognize the document, set that recognition aside and judge only the text in front of you.

Hawkish means the text points toward tighter monetary policy: higher policy rates, more or earlier increases, fewer or later cuts, a smaller balance sheet or faster runoff, or more concern about inflation than about employment. Dovish means the opposite. Judge direction relative to the stance the document itself describes; for example, holding rates high while signaling coming cuts is dovish.

Score six dimensions on integers from -2 to +2 (negative dovish, positive hawkish), or null when the document does not address the dimension:
- policy_action: the decision this document announces. Minutes describe a decision announced weeks earlier and speeches announce none; use null for both unless a new decision is announced.
- forward_guidance: what the text says or implies about the future path of policy.
- inflation_assessment: how the text characterizes inflation and its outlook against the 2 percent goal. Concern about high or rising inflation is hawkish; concern about low inflation is dovish.
- activity_labor_assessment: how the text characterizes growth and the labor market. Strength that lowers the need for accommodation is hawkish; weakness is dovish.
- risk_balance: which risks the text emphasizes. Upside inflation risks are hawkish; downside risks to growth or employment are dovish.
- balance_sheet: asset purchases, reinvestment and runoff. Expansion is dovish; reduction is hawkish.

Anchors: +2 an explicit signal of tightening or forceful concern about inflation; +1 a moderate hawkish lean; 0 balanced; -1 a moderate dovish lean; -2 an explicit signal of easing or forceful concern about weakness.

overall_stance is your holistic integer judgment of the document's net policy signal, weighting forward guidance and the balance of risks most; it is not an average of the dimensions. stance_score is the same judgment on a continuous scale from -1.0 to +1.0, for finer resolution between documents with the same integer. confidence, from 0 to 1, says how clear the signal is.

policy_relevance is "high" for documents mainly about monetary policy or the economic outlook, "medium" when they are partly about it, and "low" otherwise (for example bank supervision, payments, or community development). For low-relevance documents, use null for dimensions the text does not address and keep overall_stance at 0 unless the text takes a clear policy view.

For press conferences, score the Chair's words; reporters' questions are context. For speeches, score the speaker's own views.

evidence: two to six quotes, each copied verbatim from the document (no paraphrase, no ellipses, under 40 words), each tagged with the dimension it supports or "overall". The quotes are checked programmatically against the text, so copy them exactly.

rationale: at most two sentences."""

SHIFT_SYSTEM = """\
You compare two consecutive Federal Reserve documents of the same type, for an academic study of how changes in Fed language move Treasury yields. The PREVIOUS document is the last one of its type; the CURRENT document replaced it. Markets read these documents against each other, so the question is what the change in wording signals.

Judge only the two texts. Knowledge of later events would contaminate the study; if you recognize the documents, set that aside.

shift_score, an integer from -2 to +2: how the CURRENT document's policy signal moved relative to the PREVIOUS one. Positive means more hawkish (pointing toward tighter policy: higher rates, earlier increases, fewer cuts, faster balance-sheet reduction, more inflation concern); negative means more dovish; 0 means no material change. +2 or -2 is reserved for a clear change in policy direction or guidance.

changes: up to eight material wording changes, each with the passage as it read before ("" if new), the passage as it reads now ("" if removed), and its direction ("hawkish", "dovish" or "neutral"). Copy passages verbatim from the respective document; they are checked programmatically.

rationale: at most two sentences."""

SENTENCE_SYSTEM = """\
You label sentences from Federal Reserve communication as hawkish, dovish or neutral, for a study that compares labeling methods against human annotators.

Hawkish: the sentence points toward tighter monetary policy, for example strong or improving growth and labor markets, high or rising inflation, upside inflation risks, or support for higher rates or a smaller balance sheet. Dovish: the opposite, for example weak growth, rising unemployment, low inflation, downside risks, or support for lower rates or asset purchases. Neutral: neither, or balanced, or not about the economy or policy.

Judge each sentence on its own words. Return one label per sentence id."""

_SCORE = {"type": "integer", "enum": [-2, -1, 0, 1, 2]}
_NULLABLE_SCORE = {"anyOf": [_SCORE, {"type": "null"}]}

LEVEL_SCHEMA = {
    "type": "object",
    "properties": {
        "policy_relevance": {"type": "string", "enum": ["high", "medium", "low"]},
        **{d: _NULLABLE_SCORE for d in DIMENSIONS},
        "overall_stance": _SCORE,
        "stance_score": {"type": "number"},
        "confidence": {"type": "number"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": DIMENSIONS + ["overall"]},
                    "quote": {"type": "string"},
                },
                "required": ["dimension", "quote"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "policy_relevance",
        *DIMENSIONS,
        "overall_stance",
        "stance_score",
        "confidence",
        "evidence",
        "rationale",
    ],
    "additionalProperties": False,
}

SHIFT_SCHEMA = {
    "type": "object",
    "properties": {
        "shift_score": _SCORE,
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "direction": {"type": "string", "enum": ["hawkish", "dovish", "neutral"]},
                },
                "required": ["before", "after", "direction"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["shift_score", "changes", "rationale"],
    "additionalProperties": False,
}

SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string", "enum": ["hawkish", "dovish", "neutral"]},
                },
                "required": ["id", "label"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def level_message(doc_type: str, text: str) -> str:
    return f"Document type: {DOC_LABELS[doc_type]}\n\n<document>\n{text}\n</document>"


def shift_message(doc_type: str, previous: str, current: str) -> str:
    return (
        f"Document type: {DOC_LABELS[doc_type]}\n\n<previous>\n{previous}\n</previous>\n\n"
        f"<current>\n{current}\n</current>"
    )


def sentence_message(items: list[tuple[int, str]]) -> str:
    return "\n".join(f"[{i}] {s}" for i, s in items)
