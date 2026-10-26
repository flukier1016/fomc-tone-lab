"""Assemble previously reviewed exports and an exact HEAD archive outside the repository.

First commit every source and deck change, then put the reviewed presentation PDF (docs/PRESENTATION_DESIGN.md) and
the write-up PDF (scripts/export_writeup.py) in OUT. This command refuses uncommitted tracked changes and an earlier
code ZIP in OUT, copies the committed editable deck, archives HEAD and writes a four-deliverable manifest.
Do not run `fomc slides --out docs/slides` first: it replaces the reviewed editorial decks with the standard design.
Legacy technical exports are left untouched and are not part of the active package.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slide_count(pptx: Path) -> int:
    """Read the exported presentation's count with only the standard library."""
    try:
        with zipfile.ZipFile(pptx) as deck:
            document = ET.fromstring(deck.read("ppt/presentation.xml"))
        count = len(document.findall("{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst/*"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise SystemExit(f"Cannot inspect presentation: {pptx.name}") from exc
    if not count:
        raise SystemExit(f"Presentation has no slides: {pptx.name}")
    return count


def package(out: Path, expect: str | None = None) -> None:
    out = out.expanduser().resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit("Submission PDFs and archives must stay outside the repository.")
    changed = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True)
    if changed.strip():
        raise SystemExit("Commit tracked changes first: the code ZIP and the copied deck must be the same revision.")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    short = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    if expect and not revision.startswith(expect):
        raise SystemExit(f"HEAD is {short}, not the expected revision {expect}.")
    out.mkdir(parents=True, exist_ok=True)
    older = [p.name for p in out.glob("fomc-tone-duration-*.zip") if p.name != f"fomc-tone-duration-{short}.zip"]
    if older:
        raise SystemExit(f"Archive the previous package first; {out} still holds {', '.join(sorted(older))}.")
    name = "FOMC-Tone-Lab-editable.pptx"
    shutil.copy2(ROOT / "docs/slides" / name, out / name)
    count = slide_count(out / name)
    required = [
        "FOMC-Tone-Lab.pdf",
        "FOMC-Tone-Lab-editable.pptx",
        "FOMC-Tone-Lab-writeup.pdf",
    ]
    for name in required:
        if not (out / name).is_file():
            raise SystemExit(f"Missing reviewed export: {name}")
    archive = out / f"fomc-tone-duration-{short}.zip"
    subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), "HEAD"], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as code:
        names = set(code.namelist())
        forbidden = {
            "AGENTS.md",
            "docs/HANDOFF_CODEX.md",
            "docs/HANDOFF_CLAUDE_CODE.md",
            ".env",
            "config/local.yaml",
            "data/fomc.db",
        }
        if names & forbidden or any(n.startswith("qa/") for n in names):
            archive.unlink()
            raise SystemExit("Code archive unexpectedly includes internal or local files.")
        if "deploy/fomc.db.gz" not in names:
            raise SystemExit("The code archive must include its demo database snapshot.")
    required.append(archive.name)
    descriptions = [
        f"Unified presentation, {count} self-contained slides integrating the introduction, methods, "
        "results and implementation",
        "The same presentation as an editable PowerPoint: text, tables and method steps are native; "
        "charts are pictures",
        "Research write-up",
        "Complete code and demo snapshot at the exact revision below",
    ]
    files = "\n".join(f"| `{n}` | {d} |" for n, d in zip(required, descriptions))
    manifest = f"""# FOMC Tone Lab: unified presentation submission

IEOR 4723, Final Project Group 2: Genie Zhang, Hong-syuan Lin, Myron Pang, Weijun Situ.

Deadline: **27 October 2026, 11:59 p.m. America/New_York (EDT)**. One submission per group.
Research results frozen on **21 October 2026**. Code revision: `{revision}`.

| File | Purpose |
|---|---|
{files}

## Five-minute reproduction

Requires Python 3.11 or newer (3.12 recommended) and `make`. `make setup` uses uv when it is installed and
otherwise `python3 -m venv`; macOS ships Python 3.9, so install Python 3.12 or uv first.
Extract the code ZIP into a fresh folder, or clone the public repository below (the same files), open a terminal
there, then run:

```bash
make setup
make test
make demo-data && make serve
```

Open <http://127.0.0.1:8000>. The shipped snapshot includes the research results and model records;
no API key, paid scoring or model training is needed. `make demo-data` replaces the local database,
so use a fresh extracted folder. Start at Home, then Research (Event study, Validity) and Duration
(Signal to exposure, Historical test). The presentation is also at <http://127.0.0.1:8000/story>.

The presentation PDF is made of page images. To search or copy its text and numbers, use the editable PPTX
or `docs/slides/outline.md` in the code ZIP, which also holds the speaker notes and sources.

Public read-only demonstration: <https://fedtone.web.app>.
Public repository: <https://github.com/flukier1016/fomc-tone-lab>, holding the same files as the code ZIP.
Backup: <https://fomc-tone-lab-production.up.railway.app>.
The live site can receive later operational updates; the submitted files define the reported results.

H1 is supported on public expert labels (p = 0.004); the post-cutoff human test was not run.
Public labels may be in training data. Masked/raw agreement (r = 0.99) only partly addresses that risk.
H2 is release-window association evidence; H3's pre-registered daily trade is not supported.

Upload the slides, code ZIP and write-up as the course requires; the repository link above can accompany them.
`SHA256SUMS.txt` records integrity checks for these four active deliverables.
There is one presentation: its introduction, research methods, results and technical implementation form a single deck.
Any legacy technical exports retained elsewhere are historical copies, not additional submission requirements.
"""
    (out / "SUBMISSION.md").write_text(manifest)
    checksums = [f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}" for n in required]
    (out / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n")
    print(
        f"Submission package: {out}\nCode revision: {short}\n"
        f"{len(required)} deliverable files plus manifest and checksums"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--revision", help="refuse unless HEAD starts with this commit hash")
    args = parser.parse_args()
    package(args.out, args.revision)
