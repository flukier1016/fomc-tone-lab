"""Screenshots of a running dashboard: README images (docs/img) and the Story's product slide (web/img).

make serve                                # in one terminal
python scripts/screenshots.py             # needs Google Chrome or Chromium
python scripts/screenshots.py --base http://127.0.0.1:8765

README pages are captured whole (a long image of the full page, 1440 CSS pixels wide at 1.5x), through the
Chrome DevTools Protocol: load the page, measure its height, grow the viewport to it, then capture. The
product-slide images in web/img keep a fixed 1440 x 1000 frame.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

from fomc.slides import chrome_path, shot

ROOT = Path(__file__).resolve().parents[1]
PAGES = [  # README images, all in the light theme: easier to read on GitHub in either mode
    "overview", "fed", "tracker", "event-study", "backtest", "forecast", "validity",
    "label", "documents", "pipeline", "live", "system", "duration",
]  # fmt: skip
SIZE = (1440, 1000)  # CSS pixels for the fixed frames
SLIDE_SHOTS = ["documents", "fed", "duration", "pipeline"]  # light versions go on the product slide


async def _capture(ws_url: str, url: str, width: int, scale: float, settle: float) -> bytes:
    async with websockets.connect(ws_url, max_size=None) as ws:
        seq = 0

        async def call(method: str, **params) -> dict:
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id": seq, "method": method, "params": params}))
            while True:  # events arrive in between; keep the reply to this call
                msg = json.loads(await ws.recv())
                if msg.get("id") == seq:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        async def height() -> int:
            r = await call("Runtime.evaluate", expression="document.documentElement.scrollHeight", returnByValue=True)
            return int(r["result"]["value"])

        async def frame(h: int) -> None:
            metrics = {"width": width, "height": h, "deviceScaleFactor": scale, "mobile": False}
            await call("Emulation.setDeviceMetricsOverride", **metrics)

        await call("Page.enable")
        await frame(1000)
        await call("Page.navigate", url=url)
        await asyncio.sleep(settle)  # data, charts and their entry animations
        h = await height()
        for _ in range(3):  # a taller frame can reflow the page; settle on a stable height
            await frame(h)
            await asyncio.sleep(1.2)
            new = await height()
            if new == h:
                break
            h = new
        shot_ = await call("Page.captureScreenshot", format="png")
        return base64.b64decode(shot_["data"])


def full_page(url: str, out: Path, width: int = 1440, scale: float = 1.5, settle: float = 4.0) -> Path:
    """A long screenshot of the whole page."""
    profile = Path(tempfile.mkdtemp(prefix="fomc-shot-"))
    args = [chrome_path(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=0"]
    args += ["--remote-allow-origins=*", f"--user-data-dir={profile}", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port_file = profile / "DevToolsActivePort"
        for _ in range(100):
            if port_file.exists() and port_file.read_text().strip():
                break
            time.sleep(0.1)
        port = port_file.read_text().split()[0]
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
        ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
        out.write_bytes(asyncio.run(_capture(ws_url, url, width, scale, settle)))
        Image.open(out).save(out, optimize=True)
        return out
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--pages", nargs="*", default=PAGES, help="README pages to capture (default: all)")
    a = ap.parse_args()
    img, web = ROOT / "docs/img", ROOT / "src/fomc/web/img"
    web.mkdir(exist_ok=True)
    for page in a.pages:
        full_page(f"{a.base}/?theme=light#/{page}", img / f"{page}.png")
        print("docs/img/" + page + ".png")
    for page in SLIDE_SHOTS:
        tmp = web / f"{page}.png"
        shot(f"{a.base}/?theme=light#/{page}", tmp, SIZE)
        Image.open(tmp).convert("RGB").resize((1440, 1000), Image.LANCZOS).save(
            web / f"{page}.jpg", quality=80, optimize=True
        )
        tmp.unlink()
        print("src/fomc/web/img/" + page + ".jpg")


if __name__ == "__main__":
    main()
