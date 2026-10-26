"""Bundle the vendored Lucide icons (ISC) into one SVG sprite the dashboard inlines.

    python scripts/build_icons.py    # after adding an icon to src/fomc/web/vendor/icons/
Icons come from lucide-static 0.460.0: https://unpkg.com/lucide-static@0.460.0/icons/<name>.svg
"""

import re
from pathlib import Path

ICONS = Path(__file__).resolve().parents[1] / "src/fomc/web/vendor/icons"


def main() -> None:
    symbols = []
    for svg in sorted(ICONS.glob("*.svg")):
        if svg.name == "sprite.svg":
            continue
        body = re.search(r"<svg[^>]*>(.*)</svg>", svg.read_text(), re.S).group(1)
        body = " ".join(line.strip() for line in body.strip().splitlines())
        symbols.append(f'<symbol id="i-{svg.stem}" viewBox="0 0 24 24">{body}</symbol>')
    sprite = (
        "<!-- Lucide icons (ISC license, see LICENSE in this folder) -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">\n'
        + "\n".join(symbols)
        + "\n</svg>\n"
    )
    (ICONS / "sprite.svg").write_text(sprite)
    print(f"{len(symbols)} icons -> {ICONS / 'sprite.svg'}")


if __name__ == "__main__":
    main()
