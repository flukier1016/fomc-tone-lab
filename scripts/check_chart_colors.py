"""Verify the active press-conference chart tokens against the other series.

Machado, Oliveira and Fernandes (2009), full-severity simulation matrices:
https://raw.githubusercontent.com/njsmith/colorspacious/master/colorspacious/cvd.py
OKLab linear-sRGB transforms: https://bottosson.github.io/posts/oklab/
WCAG relative luminance: https://www.w3.org/TR/WCAG22/#dfn-relative-luminance

The thresholds below are explicit project checks, not a certification of accessibility.
"""

import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MATRICES = {
    "normal": np.eye(3),
    "protanopia": np.array(
        [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]
    ),
    "deuteranopia": np.array(
        [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]
    ),
    "tritanopia": np.array(
        [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]
    ),
}
LMS = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
LAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
CONTRAST_MIN, DISTANCE_MIN = 3.0, 0.10


def linear(hex_color):
    rgb = np.array([int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)])
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def contrast(a, b):
    ys = [float(np.dot(linear(h), [0.2126, 0.7152, 0.0722])) for h in (a, b)]
    return (max(ys) + 0.05) / (min(ys) + 0.05)


def oklab(hex_color, matrix):
    return LAB @ np.cbrt(LMS @ np.clip(matrix @ linear(hex_color), 0, 1))


def main():
    css = (ROOT / "src/fomc/web/styles.css").read_text()
    selectors = {"light": r":root\s*\{([^}]+)\}", "dark": r':root\[data-theme="dark"\]\s*\{([^}]+)\}'}
    print("| Theme | Presser | Surface contrast (>=3) | Comparison | OKLab distance (>=.10) | Simulation | Pass |")
    print("|---|---|---:|---|---:|---|---|")
    passed = True
    for theme, selector in selectors.items():
        tokens = {
            name: color
            for block in re.findall(selector, css)
            for name, color in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block)
        }
        presser = tokens["t-presser"]
        minimum_contrast = min(contrast(presser, tokens[t]) for t in ("bg", "surface", "surface-2"))
        for other in ("t-statement", "t-minutes", "t-speech", "claude"):
            distances = {
                name: float(np.linalg.norm(oklab(presser, matrix) - oklab(tokens[other], matrix)))
                for name, matrix in MATRICES.items()
            }
            worst = min(distances, key=distances.get)
            ok = minimum_contrast >= CONTRAST_MIN and distances[worst] >= DISTANCE_MIN
            passed &= ok
            print(
                f"| {theme} | {presser} | {minimum_contrast:.2f} | {other} | "
                f"{distances[worst]:.3f} | {worst} | {'yes' if ok else 'no'} |"
            )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
