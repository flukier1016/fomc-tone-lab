"""FOMC-RoBERTa: the hawkish-dovish classifier released by the Trillion Dollar Words authors, as an extra yardstick.

It is RoBERTa-large fine-tuned on their hand-labeled FOMC sentences, the corpus our 496 test sentences come from,
and its model card does not say whether training left that split out: read its score on them as an upper bound.
It needs PyTorch and transformers (`pip install -e .[roberta]`), so it runs once, offline (`fomc roberta`), and
writes its predictions to data/baselines/fomc-roberta.json (committed) with the model's revision; the pipeline reads
that file without either library. It stays outside H1's comparison, the event study and the backtest, so the tests
stated in advance and the search they are charged for are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import numpy as np

from .config import DATA
from .textutil import sentences

MODEL = "gtfintechlab/FOMC-RoBERTa"
NAME = "fomc_roberta"  # its method name in the validity table
OUT = DATA / "baselines" / "fomc-roberta.json"
TYPES = ("statement", "minutes")  # the documents it reads; every speech would take hours on a laptop


def _digest(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]


def run(batch: int = 32) -> dict:
    """Label the test split and score statements and minutes (mean of P(hawkish) - P(dovish) over sentences, the
    embedding baseline's aggregation)."""
    import torch
    from huggingface_hub import model_info
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from . import collect, supervised
    from .llm.scorer import texts_for

    revision = model_info(MODEL).sha
    tok = AutoTokenizer.from_pretrained(MODEL, revision=revision)
    net = AutoModelForSequenceClassification.from_pretrained(MODEL, revision=revision).eval()
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    net.to(device)

    def probs(texts: list[str]) -> np.ndarray:  # columns follow the dataset's codes: dovish, hawkish, neutral
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = tok(texts[i : i + batch], padding=True, truncation=True, max_length=256, return_tensors="pt")
                out.append(torch.softmax(net(**enc.to(device)).logits, dim=-1).cpu().numpy())
        return np.vstack(out) if out else np.zeros((0, 3))

    test = supervised.load_tdw("test")["sentence"].tolist()
    p = probs(test)
    docs = collect.usable()
    docs = docs[docs["doc_type"].isin(TYPES)]
    texts = texts_for(docs)
    documents = {}
    for d in docs["doc_id"]:
        q = probs(sentences(texts[d]))
        documents[d] = {"score": round(float((q[:, 1] - q[:, 0]).mean()), 6) if len(q) else 0.0, "sentences": len(q)}
    record = {
        "model": MODEL,
        "revision": revision,
        "labels": net.config.id2label,
        "device": device,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tdw_test": {"sentences_sha": _digest(test), "labels": p.argmax(1).tolist(), "probs": np.round(p, 5).tolist()},
        "documents": documents,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1))
    return record


def load(path=OUT) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def sentence_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def test_labels(test_sentences: list[str], path=OUT) -> list[int] | None:
    """A saved reader's labels for the test split, if its run read exactly these sentences."""
    rec = load(path)
    if rec and rec["tdw_test"]["sentences_sha"] == _digest(test_sentences):
        return rec["tdw_test"]["labels"]
    return None


def team_labels(team_sentences: list[str], path=OUT) -> list[int] | None:
    """A saved reader's labels for the team's sentences, if it has read every one of them."""
    got = ((load(path) or {}).get("team") or {}).get("labels", {})
    keys = [sentence_key(s) for s in team_sentences]
    return [got[k] for k in keys] if keys and all(k in got for k in keys) else None


def describe(claude: dict[str, float], doc_types: dict[str, str], path=OUT) -> dict:
    """What the Validity page shows about a saved reader: how closely its document scores track Claude's, by
    document type (Pearson and Spearman), and for the reader trained here, every setting tried and the one chosen."""
    rec = load(path)
    if not rec:
        return {}
    out = {"model": rec["model"], "revision": rec["revision"], "types": {}}
    if "search" in rec:
        out["chosen"] = rec["chosen"]
        out["search"] = [{k: r[k] for k in ("config", "best_epoch", "cv_macro_f1", "fold_sd")} for r in rec["search"]]
    out["scores"] = {d: v["score"] for d, v in rec["documents"].items() if d in claude}  # for the Story's scatter
    for t in ("statement", "minutes", "presser", "speech"):
        ids = [d for d in rec["documents"] if doc_types.get(d) == t and d in claude]
        if len(ids) < 10:
            continue
        a = np.array([rec["documents"][d]["score"] for d in ids])
        b = np.array([claude[d] for d in ids])
        ranks = [np.argsort(np.argsort(x)) for x in (a, b)]
        out["types"][t] = {
            "n": len(ids),
            "pearson": round(float(np.corrcoef(a, b)[0, 1]), 3),
            "spearman": round(float(np.corrcoef(*ranks)[0, 1]), 3),
        }
    return out
