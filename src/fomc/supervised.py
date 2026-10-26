"""Baseline 2: TF-IDF + logistic regression trained on human labels.

Labels: Trillion Dollar Words (Shah, Paturi and Chava, ACL 2023), 2,480
hand-labeled FOMC sentences, CC BY-NC 4.0. Coding: 0 dovish, 1 hawkish,
2 neutral. The model is trained on their train split only; their test split
is the shared yardstick for every method in evaluate/validity.py.
"""

from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline

from . import http
from .config import PROCESSED
from .textutil import sentences

TDW = "https://huggingface.co/datasets/gtfintechlab/fomc_communication/resolve/main/{split}.csv"
LABELS = {0: "dovish", 1: "hawkish", 2: "neutral"}


def load_tdw(split: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(http.get(TDW.format(split=split))))
    return df[["sentence", "year", "label"]]


def train() -> Pipeline:
    data = load_tdw("train")
    pipe = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]
    )
    search = GridSearchCV(pipe, {"lr__C": [0.5, 1, 2, 4, 8]}, scoring="f1_macro", cv=5)
    search.fit(data["sentence"], data["label"])
    (PROCESSED / "supervised_cv.json").write_text(
        json.dumps({"best_C": search.best_params_["lr__C"], "cv_macro_f1": search.best_score_}, indent=2)
    )
    return search.best_estimator_


def document_score(model: Pipeline, text: str) -> dict:
    sents = sentences(text)
    if not sents:
        return {"score": 0.0, "n_sentences": 0}
    proba = model.predict_proba(sents)
    cols = list(model.classes_)
    net = proba[:, cols.index(1)] - proba[:, cols.index(0)]  # P(hawkish) - P(dovish)
    return {"score": float(np.mean(net)), "n_sentences": len(sents)}


def score_documents(model: Pipeline, docs: pd.DataFrame, texts: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{"doc_id": d, **document_score(model, texts[d])} for d in docs["doc_id"]])
