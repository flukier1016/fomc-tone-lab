"""Record how many tests pytest collects in each file, for the deck's test slide.

The hosted image ships src/ but not tests/, so the Story reads these counts from src/fomc/test_inventory.json.
tests/test_submission.py checks that the file matches the suite; after adding tests, run `make inventory`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/fomc/test_inventory.json"


def collect() -> dict:
    """{"tests": total, "by_file": {file name: count}} as pytest collects them, parametrized cases included."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    by = Counter(Path(line.split("::", 1)[0]).name for line in out.splitlines() if "::" in line)
    return {"tests": sum(by.values()), "by_file": dict(sorted(by.items()))}


if __name__ == "__main__":
    OUT.write_text(json.dumps(collect(), indent=2) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {json.loads(OUT.read_text())['tests']} tests")
