"""Turn a finalized editorial build into the delivered files, after its pages have been reviewed.

Writes the two PowerPoints to docs/slides with the deck's own document properties (title, authors, slide count)
in place of the exporter's, the text outline and the contact sheet next to them, and the page-image PDF with one
bookmark per slide to --pdf, which must lie outside the repository. Nothing else in the decks changes.

Usage, after render_presentation.py, export_presentation.mjs and finalize_presentation.mjs
(docs/PRESENTATION_DESIGN.md):
  .venv/bin/python scripts/assemble_presentation.py qa/<work> --pdf /path/outside/the/repository/FOMC-Tone-Lab.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from fomc.slides import contact_sheet, outline, pdf

ROOT = Path(__file__).resolve().parents[1]
DECKS = ("FOMC-Tone-Lab-editable.pptx", "FOMC-Tone-Lab.pptx")


def _set(xml: str, tag: str, value: str) -> str:
    """Replace the text of one element, whatever its namespace prefix; the element must exist."""
    pattern = re.compile(rf"(<(?:\w+:)?{tag}(?:\s[^>]*)?>)[^<]*(</(?:\w+:)?{tag}>)")
    new, n = pattern.subn(lambda m: m.group(1) + escape(value) + m.group(2), xml, count=1)
    if n != 1:
        raise SystemExit(f"Document properties have no {tag} element to set.")
    return new


def properties(src: Path, dst: Path, story: dict) -> None:
    """Copy a deck entry by entry, rewriting only docProps/core.xml and docProps/app.xml."""
    count = len(story["slides"])
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / dst.name
        with zipfile.ZipFile(src) as deck, zipfile.ZipFile(staged, "w") as out:
            for item in deck.infolist():
                data = deck.read(item.filename)
                if item.filename == "docProps/core.xml":
                    text = data.decode("utf-8-sig")
                    text = _set(text, "title", "FOMC Tone Lab")
                    text = _set(text, "creator", ", ".join(story["team"]))
                    text = _set(text, "lastModifiedBy", "Final Project Group 2")
                    data = text.encode("utf-8")
                elif item.filename == "docProps/app.xml":
                    text = data.decode("utf-8-sig")
                    text = _set(text, "Application", "FOMC Tone Lab")
                    text = _set(text, "PresentationFormat", "Widescreen")
                    text = _set(text, "Slides", str(count))
                    text = _set(text, "Notes", str(count))
                    data = text.encode("utf-8")
                out.writestr(item, data)
        shutil.copyfile(staged, dst)


def assemble(work: Path, pdf_out: Path) -> None:
    work, pdf_out = work.resolve(), pdf_out.expanduser().resolve()
    if pdf_out == ROOT or ROOT in pdf_out.parents:
        raise SystemExit("The PDF is a delivery file: write it outside the repository.")
    story = json.loads((work / "build/story.json").read_text())
    pages = json.loads((work / "build/render-manifest.json").read_text())
    images = {int(n): Path(p) for n, p in pages.items()}
    if sorted(images) != [s["n"] for s in story["slides"]]:
        raise SystemExit("The rendered pages do not match the story's slides.")
    slides = ROOT / "docs/slides"
    for name in DECKS:
        properties(work / "final" / name, slides / name, story)
    outline(story, slides / "outline.md")
    contact_sheet(images, slides / "contact-sheet.jpg")
    pdf(images, pdf_out, story)
    print(f"{len(images)} slides: {', '.join(DECKS)}, outline.md and contact-sheet.jpg in docs/slides; {pdf_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("work", type=Path, help="the finalized work folder")
    parser.add_argument("--pdf", type=Path, required=True, help="where to write the presentation PDF")
    args = parser.parse_args()
    assemble(args.work, args.pdf)
