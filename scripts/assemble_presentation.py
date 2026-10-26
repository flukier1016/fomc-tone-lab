"""Turn a finalized editorial build into the delivered files, after its pages have been reviewed.

Writes the two PowerPoints to docs/slides with the deck's own document properties (title, authors, slide count)
in place of the exporter's and table borders every presentation program reads alike, the text outline and the
contact sheet next to them, and the presentation PDF, without bookmarks, to --pdf, which must lie outside the
repository. The PDF is the editable deck converted by LibreOffice (headless), so its text can be selected and
searched; without LibreOffice it falls back to the reviewed page images.

Usage, after render_presentation.py, export_presentation.mjs and finalize_presentation.mjs
(docs/PRESENTATION_DESIGN.md):
  .venv/bin/python scripts/assemble_presentation.py qa/<work> \
    --pdf /path/outside/the/repository/group2-final-project-01-slides.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from fomc.slides import contact_sheet, outline, pdf

ROOT = Path(__file__).resolve().parents[1]
DECKS = ("FOMC-Tone-Lab-editable.pptx", "FOMC-Tone-Lab.pptx")
SOFFICE = ("/Applications/LibreOffice.app/Contents/MacOS/soffice", "soffice", "libreoffice")
NO_GRID = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # PowerPoint's built-in "No Style, No Grid" table style
ZERO_LINE = re.compile(r'<a:ln([LRTB]) w="0"><a:noFill ?/></a:ln\1>')


def _plain_tables(xml: str) -> str:
    """Cell borders say "none" without a zero width, and tables name the no-grid style: PowerPoint read the
    exporter's zero-width borders as intended, but LibreOffice and Keynote drew a black grid over them."""
    xml = ZERO_LINE.sub(r"<a:ln\1><a:noFill/></a:ln\1>", xml)
    return xml.replace("<a:tblPr />", f"<a:tblPr><a:tableStyleId>{NO_GRID}</a:tableStyleId></a:tblPr>")


def _set(xml: str, tag: str, value: str) -> str:
    """Replace the text of one element, whatever its namespace prefix; the element must exist."""
    pattern = re.compile(rf"(<(?:\w+:)?{tag}(?:\s[^>]*)?>)[^<]*(</(?:\w+:)?{tag}>)")
    new, n = pattern.subn(lambda m: m.group(1) + escape(value) + m.group(2), xml, count=1)
    if n != 1:
        raise SystemExit(f"Document properties have no {tag} element to set.")
    return new


def properties(src: Path, dst: Path, story: dict) -> None:
    """Copy a deck entry by entry, rewriting docProps/core.xml, docProps/app.xml and the slides' table borders."""
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
                elif re.fullmatch(r"ppt/slides/slide\d+\.xml", item.filename):
                    data = _plain_tables(data.decode("utf-8")).encode("utf-8")
                out.writestr(item, data)
        shutil.copyfile(staged, dst)


def text_pdf(deck: Path, out: Path, story: dict) -> bool:
    """The editable deck as a PDF with real text and no bookmarks (46 were too many to be useful); False when
    LibreOffice is not installed."""
    from pypdf import PdfWriter

    soffice = next((p for p in (shutil.which(c) or c for c in SOFFICE) if Path(p).is_file()), None)
    if not soffice:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        profile = (Path(tmp) / "profile").as_uri()  # a private profile, so a running LibreOffice is not disturbed
        cmd = [soffice, "--headless", "--norestore", f"-env:UserInstallation={profile}", "--convert-to", "pdf"]
        subprocess.run([*cmd, "--outdir", tmp, str(deck)], check=True, capture_output=True, timeout=900)
        doc = PdfWriter()
        doc.append(str(Path(tmp) / f"{deck.stem}.pdf"), import_outline=False)
    if len(doc.pages) != len(story["slides"]):
        raise SystemExit(f"LibreOffice wrote {len(doc.pages)} pages for {len(story['slides'])} slides.")
    cover = story["slides"][0].get("subtitle", "")
    doc.add_metadata({"/Title": "FOMC Tone Lab", "/Author": ", ".join(story["team"]), "/Subject": cover})
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        doc.write(f)
    return True


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
    kind = "text" if text_pdf(slides / DECKS[0], pdf_out, story) else "page-image"
    if kind == "page-image":
        pdf(images, pdf_out, story)
    print(f"{len(images)} slides: {', '.join(DECKS)}, outline.md and contact-sheet.jpg in docs/slides")
    print(f"{kind} PDF: {pdf_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("work", type=Path, help="the finalized work folder")
    parser.add_argument("--pdf", type=Path, required=True, help="where to write the presentation PDF")
    args = parser.parse_args()
    assemble(args.work, args.pdf)
