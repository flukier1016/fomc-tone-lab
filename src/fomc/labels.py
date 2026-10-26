"""Team annotation: a yardstick no model can have memorized.

The Trillion Dollar Words labels have been public since 2023, so a model may
have seen them. These sentences come from documents released after the scoring
model's knowledge cutoff instead. Each teammate labels on their own (-1 dovish,
0 neutral, +1 hawkish). Agreement between people (Cohen's kappa) is the ceiling
a method can be expected to reach; each method is scored against the majority
label.

Labels travel in git: every label or undo rewrites data/labels/<annotator>.csv, and `import_files` loads every
teammate's file into the local store, matching sentences by their text so item ids may differ between machines.

Sampling is stratified by document type (round robin, with a per-document cap so
one long set of minutes cannot dominate) and keeps sentences that mention
policy, the economy or prices, the way the Trillion Dollar Words authors
filtered theirs; procedural lines (votes, names) are left out.
"""

from __future__ import annotations

import hashlib
import json
import re
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from . import db
from .config import LABELS_DIR, settings
from .textutil import sentences

TDW_TO_STANCE = {0: -1, 1: 1, 2: 0}  # Trillion Dollar Words coding -> stance
STANCE_NAMES = {-1: "dovish", 0: "neutral", 1: "hawkish"}
TYPES = ("statement", "minutes", "presser", "speech")
PER_DOC = {"statement": 40, "minutes": 15, "presser": 15, "speech": 4}
_PROCEDURAL = re.compile(
    r"^(Voting|Voted|Implementation Note|For release)|\bvoted\b|\b[A-Z]\.$|"
    r"\b(Advis[eo]r|Director|Economist|Secretary|Officer|Counsel|Vice President|Division of)\b"
)
_POLICY = re.compile(
    r"inflation|price|rate|policy|monetary|employment|unemployment|labor|wage|growth|economy|economic|"
    r"demand|spending|outlook|financial conditions|balance sheet|tighten|accommodat|restrictive|tariff",
    re.I,
)


def cohen_kappa(a, b) -> float:
    """Agreement beyond chance between two label vectors (numpy only: the hosted image has no scikit-learn)."""
    a, b = np.asarray(a), np.asarray(b)
    observed = float(np.mean(a == b))
    chance = sum(float(np.mean(a == c) * np.mean(b == c)) for c in np.union1d(a, b))
    if chance >= 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - chance) / (1 - chance)


def macro_f1(truth, pred) -> float:
    """Unweighted mean F1 over the classes present in either vector."""
    truth, pred = np.asarray(truth), np.asarray(pred)
    scores = []
    for c in np.union1d(truth, pred):
        tp = np.sum((pred == c) & (truth == c))
        wrong = np.sum((pred == c) & (truth != c)) + np.sum((pred != c) & (truth == c))
        scores.append(2 * tp / (2 * tp + wrong) if 2 * tp + wrong else 0.0)
    return float(np.mean(scores))


def candidates(docs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for d in docs.itertuples():
        sents = sentences(d.text or "")
        for i, sent in enumerate(sents):
            if 8 <= len(sent.split()) <= 70 and _POLICY.search(sent) and not _PROCEDURAL.search(sent):
                rows.append(
                    {
                        "doc_id": d.doc_id,
                        "doc_type": d.doc_type,
                        "position": i,
                        "sentence": sent,
                        "context_before": sents[i - 1] if i else None,
                        "context_after": sents[i + 1] if i + 1 < len(sents) else None,
                    }
                )
    return pd.DataFrame(rows)


def sample(con, n: int = 150, after: str | None = None, seed: int | None = None, batch: str = "post_cutoff") -> int:
    """Add `n` new sentences from documents released on or after `after` (default: the post-cutoff split)."""
    after = after or settings()["splits"]["post_cutoff"][0]
    seed = settings()["backtest"]["seed"] if seed is None else seed
    docs = db.query(
        con,
        f"SELECT doc_id, doc_type, text FROM documents WHERE note IS NULL AND release_date >= ? "
        f"AND doc_type IN ({','.join('?' * len(TYPES))}) ORDER BY release_date, doc_id",
        (after, *TYPES),
    )
    cand = candidates(docs)
    if cand.empty:
        return 0
    taken = {r[0] for r in con.execute("SELECT sentence FROM label_items")}
    cand = cand[~cand["sentence"].isin(taken)].drop_duplicates("sentence")
    rng = np.random.default_rng(seed + len(taken))
    cand = cand.assign(key=rng.random(len(cand))).sort_values("key")
    cand = cand[cand.groupby("doc_id").cumcount() < cand["doc_type"].map(PER_DOC)]
    queues = {t: g.to_dict("records") for t, g in cand.groupby("doc_type")}
    picked = []
    while len(picked) < n and any(queues.values()):
        for t in TYPES:
            if queues.get(t) and len(picked) < n:
                picked.append(queues[t].pop(0))
    out = pd.DataFrame(picked).drop(columns=["key", "doc_type"]).assign(batch=batch, created_at=db.now())
    return db.upsert(con, "label_items", out)


def next_item(con, annotator: str) -> dict | None:
    """The next sentence this annotator has not labeled, in a fixed shuffled order shared by everyone."""
    row = db.query(
        con,
        "SELECT i.item_id, i.doc_id, i.sentence, i.context_before, i.context_after, d.doc_type, "
        "d.release_date, d.title, d.speaker FROM label_items i JOIN documents d ON d.doc_id = i.doc_id "
        "WHERE i.item_id NOT IN (SELECT item_id FROM labels WHERE annotator = ?) "
        "ORDER BY (i.item_id * 2654435761) % 4294967296 LIMIT 1",
        (annotator,),
    )
    return None if row.empty else json.loads(row.iloc[[0]].to_json(orient="records"))[0]


def progress(con, annotator: str) -> dict:
    total = con.execute("SELECT count(*) FROM label_items").fetchone()[0]
    done = con.execute("SELECT count(*) FROM labels WHERE annotator = ?", (annotator,)).fetchone()[0]
    return {"done": done, "total": total}


def record(con, item_id: int, annotator: str, label: int) -> None:
    if label not in STANCE_NAMES:
        raise ValueError("label must be -1, 0 or 1")
    if not con.execute("SELECT 1 FROM label_items WHERE item_id = ?", (item_id,)).fetchone():
        raise KeyError(item_id)
    annotator = annotator.strip()[:40]
    con.execute("INSERT OR REPLACE INTO labels VALUES (?, ?, ?, ?)", (int(item_id), annotator, label, db.now()))
    con.commit()
    export(con, annotator)


def undo(con, annotator: str) -> int | None:
    row = con.execute(
        "SELECT item_id FROM labels WHERE annotator = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (annotator,)
    ).fetchone()
    if row:
        con.execute("DELETE FROM labels WHERE item_id = ? AND annotator = ?", (row[0], annotator))
        con.commit()
        export(con, annotator)
    return row[0] if row else None


def sentence_key(sentence: str) -> str:
    return hashlib.sha1(sentence.encode()).hexdigest()[:16]


def label_file(annotator: str) -> Path:
    return LABELS_DIR / f"{re.sub(r'[^A-Za-z0-9_-]+', '-', annotator.strip()).strip('-').lower() or 'anonymous'}.csv"


def export(con, annotator: str) -> Path:
    """Write one annotator's labels to data/labels/<annotator>.csv, the file a teammate commits to share them."""
    rows = db.query(
        con,
        "SELECT i.doc_id, l.annotator, l.label, l.created_at, i.sentence FROM labels l "
        "JOIN label_items i ON i.item_id = l.item_id WHERE l.annotator = ? ORDER BY l.created_at, i.item_id",
        (annotator,),
    )
    path = label_file(annotator)
    if rows.empty:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.insert(0, "key", rows["sentence"].map(sentence_key))
    rows.insert(4, "stance", rows["label"].map(STANCE_NAMES))
    rows.to_csv(path, index=False)
    return path


def import_files(con) -> dict:
    """Load every annotator's file into the store. A file is the record for its annotators: their labels in the
    store are replaced by the file's, so an undo on one machine reaches the others."""
    files = sorted(LABELS_DIR.glob("*.csv")) if LABELS_DIR.exists() else []
    if not files:
        return {"files": 0, "labels": 0, "unmatched": 0}
    lab = pd.concat([pd.read_csv(f, dtype={"key": str, "annotator": str}) for f in files], ignore_index=True)
    items = {sentence_key(s): i for i, s in con.execute("SELECT item_id, sentence FROM label_items")}
    lab["item_id"] = lab["key"].map(items)
    matched = lab.dropna(subset=["item_id"])
    for name in lab["annotator"].unique():
        con.execute("DELETE FROM labels WHERE annotator = ?", (name,))
    con.executemany(
        "INSERT OR REPLACE INTO labels VALUES (?, ?, ?, ?)",
        [(int(r.item_id), r.annotator, int(r.label), r.created_at) for r in matched.itertuples()],
    )
    con.commit()
    return {"files": len(files), "labels": len(matched), "unmatched": int(lab["item_id"].isna().sum())}


def majority(con) -> pd.Series:
    """Majority label per item; ties are left out. With one annotator, that annotator's label."""
    lab = db.query(con, "SELECT item_id, label FROM labels")
    if lab.empty:
        return pd.Series(dtype=float)
    counts = lab.groupby(["item_id", "label"]).size().unstack(fill_value=0)
    top = counts.max(axis=1)
    unique = (counts.eq(top, axis=0)).sum(axis=1) == 1
    return counts[unique].idxmax(axis=1)


def predict(con, sup_model=None, extra: dict | None = None) -> int:
    """Store dictionary (and, given trained models, supervised and embedding) labels for every item."""
    from . import dictionary

    items = db.query(con, "SELECT item_id, sentence FROM label_items")
    if items.empty:
        return 0
    frames = [items.assign(method="dictionary", label=items["sentence"].map(dictionary.sentence_label))]
    if sup_model is not None:
        frames.append(items.assign(method="supervised", label=sup_model.predict(items["sentence"])))
    for name, fn in (extra or {}).items():
        frames.append(items.assign(method=name, label=fn(items["sentence"].tolist())))
    out = pd.concat(frames)
    out["label"] = out["label"].map(TDW_TO_STANCE)
    return db.upsert(con, "label_predictions", out[["item_id", "method", "label"]])


def sync_llm(con, models: list[str]) -> int:
    """Mirror Claude's labels for the team sentences (`fomc llm-submit --what team`) into label_predictions."""
    from .evaluate.validity import llm_sentence_labels

    rows = [
        {"item_id": i, "method": f"llm:{m}", "label": TDW_TO_STANCE[code]}
        for m in models
        for i, code in llm_sentence_labels(m, prefix="team").items()
    ]
    return db.upsert(con, "label_predictions", pd.DataFrame(rows)) if rows else 0


def summary(con) -> dict:
    items = con.execute("SELECT count(*) FROM label_items").fetchone()[0]
    by_type = db.query(
        con,
        "SELECT d.doc_type, count(*) AS n FROM label_items i JOIN documents d ON d.doc_id = i.doc_id GROUP BY 1",
    )
    lab = db.query(con, "SELECT item_id, annotator, label FROM labels")
    annotators = [
        {"annotator": a, "n": int(n)} for a, n in lab.groupby("annotator").size().sort_values(ascending=False).items()
    ]
    pairs = []
    if len(lab):
        wide = lab.pivot_table(index="item_id", columns="annotator", values="label")
        for a, b in combinations(wide.columns, 2):
            both = wide[[a, b]].dropna()
            if len(both) >= 10:
                pairs.append(
                    {
                        "a": a,
                        "b": b,
                        "n": len(both),
                        "agreement": float((both[a] == both[b]).mean()),
                        "kappa": cohen_kappa(both[a], both[b]),
                    }
                )
    maj = majority(con)
    methods = []
    if len(maj):
        pred = db.query(con, "SELECT item_id, method, label FROM label_predictions")
        for m, g in pred.groupby("method"):
            g = g.set_index("item_id")["label"].reindex(maj.index).dropna()
            if len(g) >= 10:
                truth = maj.loc[g.index]
                methods.append(
                    {
                        "method": m,
                        "n": len(g),
                        "accuracy": float((g == truth).mean()),
                        "macro_f1": macro_f1(truth, g),
                        "kappa": cohen_kappa(truth, g),
                    }
                )
        methods.sort(key=lambda r: -r["macro_f1"])
    dist = {k: int(v) for k, v in maj.map(STANCE_NAMES).value_counts().items()} if len(maj) else {}
    return {
        "items": items,
        "by_type": [{"doc_type": t, "n": int(n)} for t, n in zip(by_type["doc_type"], by_type["n"])],
        "labels": len(lab),
        "annotators": annotators,
        "pairs": pairs,
        "majority": {"n": len(maj), "distribution": dist},
        "methods": methods,
    }
