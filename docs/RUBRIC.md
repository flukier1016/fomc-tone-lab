# Scoring rubric

The prompts and JSON schemas live in `src/fomc/llm/rubric.py`; this page explains the choices. Current version: **v1**.

## Level rubric (one document)

| Field | Scale | Meaning |
|---|---|---|
| `policy_action` | -2..+2 or null | The decision this document announces. Minutes and speeches announce none, so null. |
| `forward_guidance` | -2..+2 or null | What the text says or implies about the future path of policy. |
| `inflation_assessment` | -2..+2 or null | Inflation and its outlook against the 2 percent goal; concern about high inflation is hawkish. |
| `activity_labor_assessment` | -2..+2 or null | Growth and the labor market; strength that lowers the need for accommodation is hawkish. |
| `risk_balance` | -2..+2 or null | Which risks the text emphasizes; upside inflation risks are hawkish. |
| `balance_sheet` | -2..+2 or null | Purchases, reinvestment, runoff; expansion is dovish. |
| `overall_stance` | -2..+2 | Holistic net signal, weighting forward guidance and risks most; not an average. |
| `stance_score` | -1.0..+1.0 | The same judgment, continuous; this is the number used in the event study and backtest. |
| `confidence` | 0..1 | How clear the signal is. |
| `policy_relevance` | high, medium, low | Low for supervision, payments or community-development speeches; low documents are excluded from market tests. |
| `evidence` | 2 to 6 quotes | Verbatim, under 40 words, tagged by dimension; verified against the text after scoring. |
| `rationale` | at most two sentences | For the reader, not used in tests. |

**Direction is relative to the stance the document describes.** Holding rates at a high level while signaling cuts is dovish. This matches how a desk reads a statement: against what it implies for the path, not against zero.

## Shift rubric (two consecutive documents of the same type)

`shift_score` from -2 to +2 for how the current document's signal moved, plus up to eight changed passages quoted before and after, each tagged hawkish, dovish or neutral. Both sides are verified against their own documents.

## Sentence labels (validation only)

Hawkish, dovish or neutral per sentence, with definitions aligned to the Trillion Dollar Words annotation, so the comparison with human labels is fair.

## Why the prompts are written this way

- **The purpose is stated, not just the task.** The model is told the study tests whether text alone carries information, which is why hindsight would contaminate it. Current models follow a reason more reliably than a rule.
- **No date, no header.** The cleaned text has its date and release line removed; the model is asked to set aside recognition if it happens anyway.
- **Structured outputs, not parsing.** The schema is enforced by the API (`output_config.format`), so every response is valid JSON with the expected fields.
- **Anchors for the scale.** Plus or minus 2 is reserved for explicit signals, so the scale does not drift toward the extremes.
- **Evidence that can be checked.** Quotes are what make an LLM score auditable; the check catches invented passages.

## Changing the rubric

Edit the prompt or schema, bump `RUBRIC_VERSION`, run `fomc llm-pilot --n 8`, and record the reason below. Old records stay in their own folder.

| Version | Date | Change |
|---|---|---|
| v1 | 2026-10-18 | Initial rubric: six dimensions, holistic stance, continuous score, verified evidence; shift and sentence prompts |
