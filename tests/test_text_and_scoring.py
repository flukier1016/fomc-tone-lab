"""Text cleaning, the dictionary baseline, quote verification and the rubric schema."""

import json

from fomc import audit, dictionary, textclean
from fomc.llm import rubric
from fomc.llm.scorer import verify_quotes
from fomc.textutil import sentences

STATEMENT_HTML = b"""<html><body><div id="article">
<p>January 31, 2024</p><p>Federal Reserve issues FOMC statement</p><p>For release at 2:00 p.m. EST</p>
<p>Share</p><p>Recent indicators suggest that economic activity has been expanding at a solid pace.</p>
<p>Inflation has eased over the past year but remains elevated.</p>
<p>Voting for the monetary policy action were Jerome H. Powell, Chair; and John C. Williams, Vice Chair.</p>
<p>Implementation Note issued January 31, 2024</p></div></body></html>"""


def test_statement_header_is_stripped_and_time_kept():
    text, meta = textclean.statement_text(STATEMENT_HTML)
    assert meta["release_time_et"] == "14:00"
    assert text.startswith("Recent indicators") and "January 31, 2024" not in text
    assert text.endswith("Vice Chair.")  # nothing after the vote


def test_sentence_splitter_keeps_abbreviations():
    s = sentences("The U.S. economy grew. Inflation was 2 p.m. data. Mr. Smith spoke at length today.")
    assert s[0] == "The U.S. economy grew." and s[-1].startswith("Mr. Smith")


def test_dictionary_signs():
    assert dictionary.sentence_label("Inflation remains elevated and is rising.") == 1
    assert dictionary.sentence_label("The unemployment rate has risen sharply.") == 0
    assert dictionary.sentence_label("The Committee will meet in March.") == 2


def test_quote_verification_tolerates_typography_only():
    src = "Inflation has eased over the past year but remains elevated—for now."
    ok = verify_quotes(["inflation has eased over the past year", "remains elevated--for now"], src)
    assert ok["verified"] == 2
    bad = verify_quotes(["inflation has collapsed"], src)
    assert bad["verified"] == 0 and bad["unverified"] == ["inflation has collapsed"]


def test_schemas_are_closed_and_complete():
    for schema in (rubric.LEVEL_SCHEMA, rubric.SHIFT_SCHEMA, rubric.SENTENCE_SCHEMA, audit.IDENTIFY_SCHEMA):
        json.dumps(schema)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_anonymize_masks_dates_names_and_ranges():
    text = (
        "On January 31, 2024 the Committee kept the target range at 5-1/4 to 5-1/2 percent. "
        "Chair Powell said Jerome H. Powell agreed. In 2023 inflation was high. CHAIR POWELL. Thanks."
    )
    out = audit.anonymize(text)
    for leaked in ("2024", "2023", "January", "5-1/4", "Powell"):
        assert leaked not in out
    assert "[RANGE] percent" in out and "[DATE]" in out


def test_dictionary_spans_mark_what_word_counts_see():
    from fomc import dictionary

    text = "Inflation remains elevated. The Committee decided to lower the target range."
    got = [(text[a:b], sign) for a, b, sign in dictionary.spans(text)]
    assert got == [("Inflation remains elevated", 1), ("lower the target range", -1)]
