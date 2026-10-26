"""Headless visual review of every dashboard page: full-page captures cut into readable tiles, plus the drawers.

    .venv/bin/python scripts/review_pages.py                 # every page, four widths, into qa/review
    .venv/bin/python scripts/review_pages.py fed tracker     # only these pages
    .venv/bin/python scripts/review_pages.py --out /tmp/x    # somewhere else

Four widths: phone 390 (light), tablet 820 (dark), laptop 1366 (light), wide 1920 (dark). For each capture it prints
whether the page failed to load ("broken"), whether the page scrolls sideways, and the first elements wider than the
viewport (a table inside a scrolling box is fine there). Runs Chrome headless through the DevTools protocol, with
reduced motion, against a dashboard it starts itself: no window opens.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

import websockets
from PIL import Image

from fomc.slides import LocalServer, chrome_path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "overview", "fed", "tracker", "documents", "live", "event-study", "backtest", "duration", "forecast", "forward",
    "validity", "label", "system", "pipeline", "settings",
]  # fmt: skip
VIEWS = [  # name, theme, width, scale, mobile, tile height in CSS px
    ("phone", "light", 390, 1.5, True, 1300),
    ("tablet", "dark", 820, 1.0, True, 1400),
    ("laptop", "light", 1366, 1.0, False, 1300),
    ("wide", "dark", 1920, 0.75, False, 1500),
]
DRAWERS = [  # name, route
    ("drawer-statement", "tracker?doc=statement_20260916&full=1"),
    ("drawer-speech", "documents?doc=speech_waller20250717a"),
    ("drawer-member", "fed?member=" + quote("Christopher J. Waller") + "&full=1"),
]
CHECK = """JSON.stringify({
  broken: document.body.innerText.includes('Could not'),
  sideways: document.documentElement.scrollWidth > innerWidth + 1,
  wide: [...document.querySelectorAll('#view *, #drawer:not([hidden]) *')]
    .filter(e => e.offsetParent && e.getBoundingClientRect().right > innerWidth + 1).slice(0, 4)
    .map(e => e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0])})"""


async def capture(ws_url: str, url: str, width: int, scale: float, mobile: bool, fixed: int | None):
    async with websockets.connect(ws_url, max_size=None) as ws:
        seq = 0

        async def call(method, **params):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == seq:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        async def frame(h):
            metrics = {"width": width, "height": h, "deviceScaleFactor": scale, "mobile": mobile}
            await call("Emulation.setDeviceMetricsOverride", **metrics)

        async def height():
            r = await call("Runtime.evaluate", expression="document.documentElement.scrollHeight", returnByValue=True)
            return int(r["result"]["value"])

        await call("Page.enable")
        await call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        await frame(fixed or 1000)
        await call("Page.navigate", url=url)
        await asyncio.sleep(4.5)  # data, charts
        h = fixed or await height()
        if not fixed:  # grow the frame to the page; a taller frame can reflow it, so settle on a stable height
            for _ in range(3):
                await frame(h)
                await asyncio.sleep(1.5)
                new = await height()
                if new == h:
                    break
                h = new
        r = await call("Runtime.evaluate", expression=CHECK, returnByValue=True)
        shot = await call("Page.captureScreenshot", format="png")
        return base64.b64decode(shot["data"]), h, r["result"]["value"]


def browser():
    profile = Path(tempfile.mkdtemp(prefix="fomc-review-"))
    proc = subprocess.Popen(
        [chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=0",
         "--remote-allow-origins=*", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    port_file = profile / "DevToolsActivePort"
    for _ in range(100):
        if port_file.exists() and port_file.read_text().strip():
            break
        time.sleep(0.1)
    port = port_file.read_text().split()[0]
    targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
    return proc, profile, next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")


def save(png: bytes, out: Path, name: str, scale: float, tile: int) -> int:
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.save(out / f"{name}.png")
    step, n = int(tile * scale), 0
    for top in range(0, im.height, step):
        n += 1
        im.crop((0, top, im.width, min(im.height, top + step))).save(out / f"{name}-t{n}.png")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", help="pages to capture (default: all, plus the drawers)")
    ap.add_argument("--out", default=str(ROOT / "qa" / "review"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = a.pages or PAGES
    with LocalServer() as srv:
        base = srv.base
        jobs = [
            (f"{p}-{v}", f"{base}/?theme={t}#/{p}", w, s, m, tile, None) for p in pages for v, t, w, s, m, tile in VIEWS
        ]
        if not a.pages:  # the drawers: one frame each, on a laptop and on a phone
            jobs += [(f"{n}-laptop", f"{base}/?theme=light#/{r}", 1366, 1.0, False, 1000, 900) for n, r in DRAWERS]
            for n, r in DRAWERS:
                jobs.append((f"{n}-phone", f"{base}/?theme=dark#/{r.replace('&full=1', '')}", 390, 1.5, True, 844, 844))
        for name, url, w, s, m, tile, fixed in jobs:
            proc, profile, ws_url = browser()
            try:
                png, h, info = asyncio.run(capture(ws_url, url, w, s, m, fixed))
                print(f"{name:30s} h={h:5d} tiles={save(png, out, name, s, tile)} {info}")
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                shutil.rmtree(profile, ignore_errors=True)
    print(f"\ncaptures in {out}")


if __name__ == "__main__":
    main()
