"""Clean body text from Fed HTML pages and PDF transcripts.

The text written for scoring deliberately drops page furniture and header
facts (release date, release time, "Federal Reserve issues FOMC statement").
Those facts are returned separately so the event table can use them while the
scorer never sees a date it does not need.
"""

from __future__ import annotations

import io
import re
from collections import Counter

from bs4 import BeautifulSoup
from pypdf import PdfReader

BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre", "blockquote", "dd", "dt"]
BOILERPLATE = re.compile(
    r"^(home|share|print|search|accessibility|contact us|skip to main content|"
    r"news and events|monetary policy|\d{4} monetary policy|fomc|return to (text|top)|"
    r"last update:.*|board of governors of the federal reserve system|watch live|"
    r"for media inquiries.*|related information|back to top)$",
    re.I,
)
DATE_LINE = re.compile(r"^(release date:\s*)?[A-Z][a-z]+\.? \d{1,2}, \d{4}$")
RELEASE_TIME = re.compile(r"for release at (\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?", re.I)


def _norm(s: str) -> str:
    return " ".join(s.split())


def html_blocks(raw: bytes) -> list[str]:
    """Innermost block-level texts of the main content node, in document order."""
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form"]):
        tag.decompose()
    node = soup.select_one("#article") or soup.select_one("#content") or soup.body or soup
    blocks = []
    for el in node.find_all(BLOCK_TAGS):
        if el.find(BLOCK_TAGS):
            continue
        text = _norm(el.get_text(" "))
        if text:
            blocks.append(text)
    whole = _norm(node.get_text(" "))
    if sum(len(b) for b in blocks) < 0.6 * len(whole):
        # Old pages keep prose outside block tags; fall back to blank-line paragraphs.
        paras = re.split(r"\n\s*\n", node.get_text("\n"))
        blocks = [_norm(p) for p in paras if _norm(p)]
    return [b for b in blocks if not BOILERPLATE.match(b)]


def release_time(blocks: list[str]) -> str | None:
    """'For release at 2:00 p.m. EST' -> '14:00' (first match in the header area)."""
    for block in blocks[:8]:
        m = RELEASE_TIME.search(block)
        if m:
            hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
            if ampm == "p" and hour != 12:
                hour += 12
            if ampm == "a" and hour == 12:
                hour = 0
            return f"{hour:02d}:{minute:02d}"
    return None


def _drop_header(blocks: list[str], extra: tuple[str, ...] = ()) -> list[str]:
    out, in_header = [], True
    for b in blocks:
        if in_header and (
            DATE_LINE.match(b)
            or RELEASE_TIME.search(b)
            or re.match(r"^for immediate release", b, re.I)
            or b.lower() in ("fomc statement", "press release")
            or b.lower().startswith(
                ("federal reserve issues fomc statement", "federal reserve board and federal open market committee")
            )
            or any(b.startswith(x) for x in extra)
        ):
            continue
        in_header = False
        out.append(b)
    return out


def statement_text(raw: bytes) -> tuple[str, dict]:
    blocks = html_blocks(raw)
    meta = {"release_time_et": release_time(blocks)}
    body = [
        b
        for b in _drop_header(blocks)
        if not b.lower().startswith(("implementation note issued", "for media inquiries"))
    ]
    # The vote is the last part of a statement; anything after it is related links.
    votes = [i for i, b in enumerate(body) if b.startswith("Voting")]
    if votes:
        body = body[: votes[-1] + 1]
    return "\n\n".join(body), meta


MINUTES_START = re.compile(
    r"^(developments in financial markets|staff review of the economic|"
    r"the information reviewed (at|for) this meeting|the information received)",
    re.I,
)


def minutes_text(raw: bytes) -> tuple[str, dict]:
    """Drop the attendance list: it is long, names people and carries no stance. It led the minutes
    until mid-2024 and has closed them since. The notation vote approving the previous minutes goes
    too; intermeeting calls reported after it stay, since they discuss policy."""
    blocks = html_blocks(raw)
    start = next((i for i, b in enumerate(blocks) if MINUTES_START.match(b)), 0)
    end = next((i for i in range(start + 1, len(blocks)) if blocks[i].startswith("Attendance ")), len(blocks))
    body = [b for b in blocks[start:end] if not b.endswith("Return to text") and not b.startswith("Notation Vote")]
    return "\n\n".join(body), {"trimmed_attendance": start > 0, "trimmed_tail_blocks": len(blocks) - end}


def speech_text(raw: bytes) -> tuple[str, dict]:
    blocks = html_blocks(raw)
    # Header: date, title, speaker, venue: short lines before the first real paragraph.
    start = 0
    for i, b in enumerate(blocks[:10]):
        if len(b.split()) >= 25:
            start = i
            break
    body = blocks[start:]
    # Footnotes and references follow the text; each footnote ends in "Return to text".
    end = next(
        (
            i
            for i, b in enumerate(body)
            if b.endswith("Return to text") or re.match(r"^(References|Footnotes|Notes)(\s|$)", b)
        ),
        len(body),
    )
    return "\n\n".join(body[:end]), {"header_lines_dropped": start, "tail_blocks_dropped": len(body) - end}


SPEAKER_TURN = re.compile(r"(?<![A-Z'\-])\s(?=[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+){0,3}\. )")


def pdf_text(raw: bytes) -> str:
    """Text of a PDF with running headers, footers and page numbers removed."""
    reader = PdfReader(io.BytesIO(raw))
    pages = [(page.extract_text() or "").splitlines() for page in reader.pages]
    counts = Counter(line.strip() for lines in pages for line in set(lines) if line.strip())
    repeated = {line for line, n in counts.items() if len(pages) >= 3 and n >= 0.4 * len(pages)}
    kept = []
    for lines in pages:
        for line in lines:
            s = line.strip()
            if not s or s in repeated or re.fullmatch(r"(page )?\d+( of \d+)?", s, re.I):
                continue
            kept.append(s)
    text = " ".join(kept)
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # rejoin hyphenated line breaks
    return _norm(text)


_SPEAKER = re.compile(r"^(QUESTION|REPORTER|MODERATOR|[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+){1,3})\. ")


def presser_turns(text: str) -> list[tuple[str, str]]:
    """(speaker, words) per turn. A label is a name ("CHAIR POWELL", "MICHELLE SMITH") or the early
    transcripts' "QUESTION"; any other capitalized word before a period ("CBS.", "PCE.") is part of the
    running turn, not a new speaker."""
    turns: list[list[str]] = []
    for block in SPEAKER_TURN.sub("\n\n", text).split("\n\n"):
        block = block.strip()
        m = _SPEAKER.match(block)
        if m:
            turns.append([m.group(1), block[m.end() :]])
        elif turns:
            turns[-1][1] += " " + block
        elif block:
            turns.append(["", block])
    return [(who, words.strip()) for who, words in turns if words.strip()]


def presser_text(raw: bytes) -> tuple[str, dict]:
    """The Chair's words only: the opening statement and the answers. Reporters' questions and the
    moderator are dropped, because they are not Fed communication."""
    text = pdf_text(raw)
    text = re.sub(r"^.*?(?=CHAIR(?:MAN)? [A-Z]+\. )", "", text, count=1)  # drop the title block
    turns = presser_turns(text)
    chair = [words for who, words in turns if who.startswith("CHAIR")]
    return "\n\n".join(chair), {"turns": len(turns), "chair_turns": len(chair)}
