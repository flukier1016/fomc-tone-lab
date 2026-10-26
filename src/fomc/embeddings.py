"""Baseline 3: sentence-level embeddings.

Every sentence is embedded with all-MiniLM-L6-v2 (the Sentence-BERT family, Apache-2.0), run locally
through ONNX by fastembed: no GPU, no API, about a minute for the whole corpus. A logistic regression
trained on the Trillion Dollar Words train split maps an embedding to dovish, hawkish or neutral. A
document's score is the mean of P(hawkish) - P(dovish) over its sentences: the same aggregation as the
TF-IDF baseline, so the two differ only in how a sentence is represented.

Document scores are cached by text hash and classifier version, so a rerun embeds only new or changed
documents.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from .config import PROCESSED, RAW
from .textutil import sentences

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = PROCESSED / "embedding_scores.csv"


class SentenceEmbeddings:
    """The encoder plus the classifier trained on human labels; `encoder` can be swapped in tests."""

    def __init__(self, encoder=None):
        self.encoder = encoder
        self.clf = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.encoder is None:
            from fastembed import TextEmbedding

            self.encoder = TextEmbedding(MODEL, cache_dir=str(RAW / "models"))
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        return np.asarray(list(self.encoder.embed(texts, batch_size=256)), dtype=np.float32)

    def train(self, data: pd.DataFrame | None = None) -> SentenceEmbeddings:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GridSearchCV

        from . import supervised

        data = supervised.load_tdw("train") if data is None else data
        search = GridSearchCV(
            LogisticRegression(max_iter=3000, class_weight="balanced"),
            {"C": [0.25, 1, 4, 16]},
            scoring="f1_macro",
            cv=5,
        )
        search.fit(self.encode(data["sentence"].tolist()), data["label"])
        self.clf = search.best_estimator_
        (PROCESSED / "embedding_cv.json").write_text(
            json.dumps(
                {"model": MODEL, "best_C": search.best_params_["C"], "cv_macro_f1": search.best_score_}, indent=2
            )
        )
        return self

    @property
    def version(self) -> str:
        raw = self.clf.coef_.tobytes() + self.clf.intercept_.tobytes()
        return hashlib.sha1(MODEL.encode() + raw).hexdigest()[:12]

    def predict(self, texts: list[str]) -> np.ndarray:
        """Trillion Dollar Words codes: 0 dovish, 1 hawkish, 2 neutral."""
        return self.clf.predict(self.encode(list(texts)))

    def net(self, texts: list[str]) -> np.ndarray:
        """P(hawkish) - P(dovish) per sentence."""
        proba = self.clf.predict_proba(self.encode(list(texts)))
        cols = list(self.clf.classes_)
        return proba[:, cols.index(1)] - proba[:, cols.index(0)]

    def score_documents(self, docs: pd.DataFrame, texts: dict[str, str]) -> pd.DataFrame:
        cached = pd.read_csv(CACHE) if CACHE.exists() else pd.DataFrame(columns=["doc_id", "sha", "version"])
        keep = cached.set_index("doc_id").to_dict("index") if len(cached) else {}
        rows, todo = [], []
        for d in docs["doc_id"]:
            text = texts.get(d) or ""
            sha = hashlib.sha1(text.encode()).hexdigest()
            hit = keep.get(d)
            if hit and hit["sha"] == sha and hit["version"] == self.version:
                rows.append(
                    {"doc_id": d, "sha": sha, "version": self.version, **{k: hit[k] for k in ("score", "n_sentences")}}
                )
            else:
                todo.append((d, sha, sentences(text)))
        flat = [s for _, _, sents in todo for s in sents]
        nets = self.net(flat) if flat else np.array([])
        at = 0
        for d, sha, sents in todo:
            part = nets[at : at + len(sents)]
            at += len(sents)
            rows.append(
                {
                    "doc_id": d,
                    "sha": sha,
                    "version": self.version,
                    "score": float(part.mean()) if len(part) else 0.0,
                    "n_sentences": len(sents),
                }
            )
        out = pd.DataFrame(rows)
        out.to_csv(CACHE, index=False)
        return out[["doc_id", "score", "n_sentences"]]
