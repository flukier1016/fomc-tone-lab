"""Does each method label tone the way human annotators do?

Yardstick: the Trillion Dollar Words test split (496 hand-labeled FOMC
sentences). The supervised baseline never sees it during training. Caveat:
the dataset has been public since 2023, so an LLM may have seen it; the
post-cutoff hand-labeled set in docs/WORKFLOW.md is the clean check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix, f1_score

from .. import dictionary, supervised
from ..labels import macro_f1
from ..llm.scorer import load_records

LLM_CODES = {"dovish": 0, "hawkish": 1, "neutral": 2}


def llm_sentence_labels(model: str, prefix: str = "tdw_test") -> dict[int, int]:
    labels = {}
    for r in load_records(model, "sentences"):
        if r["status"] == "ok" and r["key"].startswith(prefix):
            labels.update({x["id"]: LLM_CODES[x["label"]] for x in r["parsed"]["labels"]})
    return labels


def compare(truth, preds: dict, target: str, n_boot: int = 2000, seed: int = 7) -> list[dict]:
    """Is `target` better than each other method on the same sentences, or just lucky on this sample?

    Paired bootstrap: resample the sentences, recompute both macro-F1s, and read the 95% interval and a two-sided
    p-value off the distribution of the difference. McNemar's exact test asks the same of accuracy, using only the
    sentences the two methods label differently (b: only `target` right; c: only the other right)."""
    truth = np.asarray(truth)
    mine = np.asarray(preds[target])
    idx = np.random.default_rng(seed).integers(0, len(truth), (n_boot, len(truth)))
    rows = []
    for name, other in preds.items():
        if name == target:
            continue
        other = np.asarray(other)
        diffs = np.array([macro_f1(truth[i], mine[i]) - macro_f1(truth[i], other[i]) for i in idx])
        b = int(np.sum((mine == truth) & (other != truth)))
        c = int(np.sum((mine != truth) & (other == truth)))
        rows.append(
            {
                "target": target,
                "method": name,
                "f1_diff": macro_f1(truth, mine) - macro_f1(truth, other),
                "ci_low": float(np.percentile(diffs, 2.5)),
                "ci_high": float(np.percentile(diffs, 97.5)),
                "p_boot": float(min(1.0, 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0)))),
                "only_target_right": b,
                "only_other_right": c,
                "mcnemar_p": float(binomtest(min(b, c), b + c, 0.5).pvalue) if b + c else 1.0,
            }
        )
    return rows


def sentence_benchmark(sup_model, llm_models: list[str] = (), extra: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """`extra` maps a method name to a function from sentences to labels (the embedding baseline). The second
    value holds the confusion matrices and, when Claude labeled every sentence, its paired tests against the rest."""
    test = supervised.load_tdw("test")
    preds = {
        "dictionary": test["sentence"].map(dictionary.sentence_label).to_numpy(),
        "supervised": sup_model.predict(test["sentence"]),
    }
    for name, fn in (extra or {}).items():
        preds[name] = fn(test["sentence"].tolist())
    for m in llm_models:
        got = llm_sentence_labels(m)
        if len(got) == len(test):
            preds[f"llm:{m}"] = [got[i] for i in range(len(test))]
    rows, confusions = [], {}
    for name, p in preds.items():
        rows.append(
            {
                "method": name,
                "n": len(test),
                "accuracy": accuracy_score(test["label"], p),
                "macro_f1": f1_score(test["label"], p, average="macro"),
                "cohen_kappa": cohen_kappa_score(test["label"], p),
            }
        )
        confusions[name] = confusion_matrix(test["label"], p, labels=[0, 1, 2]).tolist()
    llm = next((k for k in preds if k.startswith("llm:")), None)
    tests = compare(test["label"].to_numpy(), preds, llm) if llm else []
    return pd.DataFrame(rows), {"confusions": confusions, "tests": tests}
