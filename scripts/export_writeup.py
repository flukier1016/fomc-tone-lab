"""Render the submission write-up through Pandoc and XeLaTeX, in the page style of the course homework.

Usage: .venv/bin/python scripts/export_writeup.py --out /path/to/group2-final-project-03-writeup.pdf
Requires Pandoc and XeLaTeX (TeX Live or MacTeX); no network calls, API keys or research computation.
docs/WRITEUP.md stays the single source: numbered markers such as [3] become superscript citations, and its final
section becomes the numbered list of references and sources. The page design is scripts/writeup_template.tex.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fomc.config import settings

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("writeup_template.tex")
LINK = re.compile(r"\[([^\]]+)\]\((?![a-z][a-z0-9+.-]*:|#)([^)\s]+)\)")
ADDRESS = re.compile(r"\\href\{([^}]*)\}\{([^{}\s]+\.[^{}\s]+)\}")  # link text that is itself an address
CITE = re.compile(r"\{\[\}(\d+(?:,\s*\d+)*)\{\]\}")  # Pandoc's escaped [3] or [20, 28]
MINUS = re.compile(r"(?<![\w.])-(?=\d)")  # a hyphen before a number is a minus sign in running text
REFERENCES = "## References and sources"
BRACKETED = (r"\def\labelenumi{\arabic{enumi}.}", r"\def\labelenumi{[\arabic{enumi}]}")  # [1] rather than 1.
TEX_FALLBACK = Path("/Library/TeX/texbin")


def local_links(markdown: str, base: Path) -> str:
    """Links to repository files become their paths in the code archive: a PDF cannot open them."""

    def path(m: re.Match) -> str:
        text, target = m.groups()
        where = (base / target.split("#", 1)[0]).resolve().relative_to(ROOT).as_posix()
        return f"`{where}`" if text in (target, Path(target).name) else f"{text} (`{where}`)"

    return LINK.sub(path, markdown)


def minus_signs(markdown: str) -> str:
    """True minus signs in prose; code spans and code blocks keep their hyphens."""
    out, fenced = [], False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            parts = line.split("`")
            line = "`".join(MINUS.sub("\u2212", p) if i % 2 == 0 else p for i, p in enumerate(parts))
        out.append(line)
    return "\n".join(out) + "\n"


def tool(name: str) -> str:
    found = shutil.which(name) or (str(TEX_FALLBACK / name) if (TEX_FALLBACK / name).exists() else None)
    if not found:
        raise SystemExit(f"{name} is required to export the write-up (Pandoc: brew install pandoc; XeLaTeX: MacTeX).")
    return found


def latex(markdown: str) -> str:
    tex = subprocess.run(
        [
            tool("pandoc"),
            "--from=markdown+smart-implicit_figures",
            "--to=latex",
            "--wrap=none",
            "--shift-heading-level-by=-1",
            "--syntax-highlighting=none",
        ],
        input=markdown,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    tex = ADDRESS.sub(lambda m: rf"\href{{{m[1]}}}{{\nolinkurl{{{m[2].replace(chr(92) + '_', '_')}}}}}", tex)
    return CITE.sub(r"\\scite{\1}", tex).replace(r"\texttt{", r"\code{")


def document(source: Path) -> str:
    """The filled template: title and byline from the source's opening, then the body and the numbered sources."""
    text = minus_signs(local_links(source.read_text(), source.resolve().parent))
    head, body = text.split("\n## ", 1)
    body, sources = ("## " + body).split(REFERENCES, 1)
    title = head.splitlines()[0].removeprefix("# ").strip()
    byline = head.split("\n\n")[1]  # the line under the title; the note on citation numbers is for readers online
    sources = latex(REFERENCES + sources).replace(*BRACKETED)
    project = settings()["project"]
    fill = {
        "%%TITLE%%": title,
        "%%AUTHORS%%": ", ".join(project["team"]),
        "%%SUBJECT%%": project["course"],
        "%%GROUP%%": f"{project['group'].removeprefix('Final Project ')}: {', '.join(project['team'])}",
        "%%BYLINE%%": latex(byline).strip(),
        "%%BODY%%": latex(body),
        "%%SOURCES%%": sources,
    }
    out = TEMPLATE.read_text()
    for marker, value in fill.items():
        out = out.replace(marker, value)
    return out


def export(source: Path, out: Path) -> None:
    xelatex = tool("xelatex")
    with tempfile.TemporaryDirectory(prefix="fomc-writeup-") as tmp:
        tex = Path(tmp) / "writeup.tex"
        tex.write_text(document(source))
        for _ in range(2):  # the second pass settles bookmarks and the PDF outline
            run = subprocess.run(
                [xelatex, "-interaction=nonstopmode", "-halt-on-error", tex.name],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            if run.returncode:
                raise SystemExit(f"XeLaTeX failed:\n{run.stdout[-3000:]}")
        log = tex.with_suffix(".log").read_text(errors="replace")
        for warning in re.findall(r"^(Overfull \\hbox .*|Missing character.*)$", log, re.M):
            print("warning:", warning)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tex.with_suffix(".pdf"), out)
    print(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "docs/WRITEUP.md")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    export(args.source, args.out)
