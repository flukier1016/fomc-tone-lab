"""Project paths and settings. Every module imports locations from here.

Settings come from config/settings.yaml (shared, committed) deep-merged with
config/local.yaml (personal, git-ignored: model choice, effort, ...).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"  # downloaded pages and files, kept for provenance (git-ignored)
INTERIM = DATA / "interim"  # document index and clean texts
PROCESSED = DATA / "processed"  # market data, event table, baseline scores
LLM_DIR = DATA / "llm"  # raw model responses and parsed scores (committed)
LABELS_DIR = DATA / "labels"  # team labels, one CSV per annotator (committed)
RESULTS = ROOT / "results"  # tables and figures


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(ROOT / "config" / "settings.yaml") as fh:
        cfg = yaml.safe_load(fh)
    local = ROOT / "config" / "local.yaml"
    if local.exists():
        cfg = _merge(cfg, yaml.safe_load(local.read_text()) or {})
    return cfg


def reload_settings() -> None:
    settings.cache_clear()


def ensure_dirs() -> None:
    for d in (RAW, INTERIM, INTERIM / "texts", PROCESSED, LLM_DIR, RESULTS):
        d.mkdir(parents=True, exist_ok=True)
