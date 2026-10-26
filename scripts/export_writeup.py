"""Render the paginated submission write-up through Pandoc and headless Chrome.

Usage: .venv/bin/python scripts/export_writeup.py --out /path/to/FOMC-Tone-Lab-writeup.pdf
Requires Pandoc and Chrome; no network calls, API keys or research computation. Typefaces and colors come from
scripts/deck_theme.json, so the write-up matches the presentation: Georgia headings, Arial for everything else.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fomc.config import settings
from fomc.slides import chrome_path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[([^\]]+)\]\((?![a-z][a-z0-9+.-]*:|#)([^)\s]+)\)")
HEADING = re.compile(r"<h2[^>]*>(\d+)\.\s*(.*?)</h2>", re.S)
FACES = {"Georgia": 'Georgia, "Times New Roman", serif', "Arial": "Arial, Helvetica, sans-serif"}


def local_links(markdown: str, base: Path) -> str:
    """Links to repository files become their paths in the code archive: a PDF cannot open them, and a link would
    otherwise point into the temporary folder the page is printed from."""

    def path(m: re.Match) -> str:
        text, target = m.groups()
        where = (base / target.split("#", 1)[0]).resolve().relative_to(ROOT).as_posix()
        return f"`{where}`" if text in (target, Path(target).name) else f"{text} (`{where}`)"

    return LINK.sub(path, markdown)


STYLE = """
@page { size: A4; margin: 15mm; }
* { box-sizing: border-box; }
body { margin: 0; color: BODY; font: 10pt/1.42 TEXT; }
section { position: relative; min-height: 266mm; padding-bottom: 12mm; break-after: page; }
section:last-child { break-after: auto; }
.running { display: flex; justify-content: space-between; gap: 6mm; padding-bottom: 3mm; border-bottom: 1px solid RULE;
  color: LABEL; font-size: 7.5pt; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.running b { color: ACCENT; margin-right: 3mm; }
h1 { font: 400 30pt/1.1 DISPLAY; color: INK; margin: 6mm 0 3mm; letter-spacing: -.01em; }
h2 { font: 400 19pt/1.2 DISPLAY; color: INK; margin: 5mm 0 3mm; }
strong { color: INK; }
p { margin: 0 0 2.8mm; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0 4mm; font-size: 8.7pt; line-height: 1.35; }
th { background: SOFT; color: INK; text-align: left; border-bottom: 1.5px solid INK; }
td { border-bottom: .7px solid RULE; }
th, td { padding: 1.8mm 2mm; vertical-align: top; }
tr { break-inside: avoid; }
a { color: INK; text-decoration: underline; text-decoration-color: ACCENT; text-underline-offset: 2px; }
code { font: inherit; color: INK; background: SOFT; padding: 0 .08em; overflow-wrap: anywhere; }
pre { margin: 0 0 3mm; padding: 3mm 4mm; background: SOFT; border-left: 2px solid INK;
  font: 9.5pt/1.5 TEXT; }
pre code { background: none; padding: 0; }
.source { margin-top: 4mm; padding-top: 2mm; border-top: 1px solid RULE; color: LABEL; font-size: 8.5pt; }
.source code { background: none; padding: 0; color: LABEL; }
.footer { position: absolute; bottom: 0; left: 0; right: 0; border-top: 1px solid RULE;
  padding-top: 2mm; color: LABEL; font-size: 8pt; display: flex; justify-content: space-between; }
"""


def style() -> str:
    """The stylesheet in the presentation's typefaces and colors."""
    theme = json.loads((ROOT / "scripts/deck_theme.json").read_text())
    fonts, colors = theme["fonts"], theme["palette"]
    out = STYLE.replace("DISPLAY", FACES.get(fonts["display"], fonts["display"]))
    out = out.replace("TEXT", FACES.get(fonts["text"], fonts["text"]))
    for name in ("ink", "body", "label", "rule", "soft", "accent"):
        out = out.replace(name.upper(), colors[name])
    return out


def export(source: Path, out: Path, html_out: Path | None = None) -> None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("Pandoc is required to export the write-up; install it with brew install pandoc.")
    parts = local_links(source.read_text(), source.resolve().parent).split("<!-- pagebreak -->")
    pages, titles = [], []
    for i, part in enumerate(parts, 1):
        rendered = subprocess.run(
            [pandoc, "--from=gfm", "--to=html5", "--wrap=none"],
            input=part,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        heading = HEADING.search(rendered)
        number, name = (heading.group(1), re.sub(r"<[^>]+>", "", heading.group(2))) if heading else (str(i), "")
        titles.append(f"{number}. {html.unescape(name)}")
        rendered = rendered.replace("<p>Source:", '<p class="source">Source:')
        pages.append(
            f'<section><div class="running"><span><b>{int(number):02d}</b>{name}</span>'
            "<span>FOMC Tone Lab · Final Project Group 2</span></div>"
            + rendered
            + '<div class="footer"><span>Research frozen: 21 October 2026 · fedtone.web.app</span>'
            + f"<span>{i} / {len(parts)}</span></div></section>"
        )
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f"<title>FOMC Tone Lab: research write-up</title><style>{style()}</style>"
        + "<body>"
        + "".join(pages)
        + "</body></html>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fomc-writeup-") as tmp:
        page = Path(tmp) / "writeup.html"
        page.write_text(document)
        if html_out:
            html_out.parent.mkdir(parents=True, exist_ok=True)
            html_out.write_text(document)
        subprocess.run(
            [
                chrome_path(),
                "--headless=new",
                "--disable-gpu",
                f"--user-data-dir={tmp}/chrome",
                "--no-pdf-header-footer",
                "--virtual-time-budget=5000",
                f"--print-to-pdf={out.resolve()}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    bookmark(out, titles)
    print(f"{out} ({len(parts)} source pages)")


def bookmark(pdf: Path, titles: list[str]) -> None:
    """A bookmark per section, and the document's title and authors, as in the presentation PDF."""
    from pypdf import PdfWriter

    doc = PdfWriter(clone_from=pdf)
    if len(doc.pages) == len(titles):  # one section per page, as written
        for i, title in enumerate(titles):
            doc.add_outline_item(title, i)
        doc.page_mode = "/UseOutlines"
    project = settings()["project"]
    doc.add_metadata(
        {
            "/Title": "FOMC Tone Lab: research write-up",
            "/Author": ", ".join(project["team"]),
            "/Subject": project["course"],
        }
    )
    with open(pdf, "wb") as f:
        doc.write(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "docs/WRITEUP.md")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--html", type=Path)
    args = parser.parse_args()
    export(args.source, args.out, args.html)
