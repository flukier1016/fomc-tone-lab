"""Render the editorial Story and its exhibits without recomputing research.

Prepare the editable deck with the bundled Artifact Tool afterwards:
RUNTIME_NODE_MODULES=/path/to/node_modules node scripts/export_presentation.mjs WORK
"""

from __future__ import annotations

import argparse
import json
import posixpath
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fomc.slides import LocalServer, shot

ROOT = Path(__file__).resolve().parents[1]
NATIVE = {"table", "steps", "cards", "tiles", "flow", "code", "answers", "brief"}


def frame(slide):
    height = 500 if slide.get("desk") else 558
    layout = slide["layout"]
    if layout == "banner":
        return {"x": 80, "y": 372, "w": 1440, "h": height - 120}
    if layout == "wide":
        return {"x": 80, "y": 252, "w": 1440, "h": height}
    return {"x": 80 if layout == "mirror" else 488, "y": 252, "w": 1032, "h": height}


def render(work: Path):
    work = work.resolve()
    build = work / "build"
    build.mkdir(parents=True, exist_ok=True)
    source = ROOT / "docs/slides/FOMC-Tone-Lab-editable.pptx"
    with zipfile.ZipFile(source) as deck:
        ns = {
            "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        document = ET.fromstring(deck.read("ppt/presentation.xml"))
        size = document.find("p:sldSz", ns)
        cover = ET.fromstring(deck.read("ppt/slides/slide1.xml"))
        embed = cover.find(".//p:pic//a:blip", ns).get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
        )
        relationships = ET.fromstring(deck.read("ppt/slides/_rels/slide1.xml.rels"))
        target = next(r.attrib["Target"] for r in relationships if r.attrib["Id"] == embed)
        media = target.lstrip("/") if target.startswith("/") else posixpath.normpath("ppt/slides/" + target)
        logo = build / "logo.png"
        logo.write_bytes(deck.read(media))
    reference = {"path": str(source), "cx": int(size.attrib["cx"]), "cy": int(size.attrib["cy"])}
    (build / "reference.json").write_text(json.dumps(reference, indent=2))
    with LocalServer() as server:
        story = json.load(urllib.request.urlopen(server.base + "/api/story", timeout=30))
        (build / "story.json").write_text(json.dumps(story, indent=2, allow_nan=False))
        jobs = []
        frames = {}
        for slide in story["slides"]:
            n = slide["n"]
            jobs.append(
                (
                    "slide",
                    n,
                    f"{server.base}/?theme=light#/story?s={n}&export=slide",
                    build / f"web-{n:02}.png",
                    (1600, 900),
                )
            )
            visual = slide.get("visual", {})
            if visual:
                f = frame(slide)
                frames[n] = f
                if visual["kind"] not in NATIVE:
                    jobs.append(
                        (
                            "visual",
                            n,
                            f"{server.base}/?theme=light#/story?s={n}&export=visual",
                            build / f"visual-{n:02}.png",
                            (f["w"], f["h"]),
                        )
                    )

        def run(job):
            kind, n, url, destination, viewport = job
            shot(url, destination, viewport, 1.5)
            return kind, n, str(destination)

        results = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            for kind, n, destination in pool.map(run, jobs):
                results.append((kind, n, destination))
                print(f"{kind} {n}", flush=True)
    manifest = {
        "logo": str(logo),
        "frames": frames,
        "visuals": {n: p for k, n, p in results if k == "visual"},
        "images": {n: p for k, n, p in results if k == "slide"},
    }
    (build / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Prepared {len(story['slides'])} slides in {work}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="a new, empty folder under qa/ for this revision")
    render(parser.parse_args().work)
