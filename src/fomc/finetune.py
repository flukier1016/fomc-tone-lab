"""RoBERTa fine-tuned here on the TF-IDF baseline's training data: a stronger supervised reader, added later.

Same data, same rules as the TF-IDF and embedding baselines: the 1,984 Trillion Dollar Words train sentences, the
same five cross-validation folds (GridSearchCV's, in file order), the same selection score (macro-F1) and a
class-balanced loss (their class_weight="balanced"). The 496 test sentences are read once, by the chosen model.

The search: roberta-base at four learning rates and roberta-large at three, then two refinements of the best
(layer-wise learning-rate decay, batches of 32). Every run follows a ten-epoch schedule (10% warmup, linear decay)
and is scored on its validation fold after each epoch, so the number of epochs is chosen with the rest. The final
reader is five seeds of the chosen setting, refit on all 1,984 sentences, stopped at the chosen epoch of the same
schedule, with their probabilities averaged; it scores every document the way the other baselines do (the mean of
P(hawkish) - P(dovish) over its sentences). Every run is kept in data/baselines/roberta-tuned.json with the
backbones' revisions.

It stays outside H1, the event study and the backtest: those were stated against three baselines, and this one came
after the results. Needs PyTorch and transformers (`pip install -e .[roberta]`); on an M4 Pro laptop `fomc finetune`
takes about five hours for the search and two for the five final readers, and resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime

import numpy as np

from .config import DATA, PROCESSED, ROOT
from .labels import macro_f1

NAME = "roberta_tuned"  # its method name in the validity table
OUT = DATA / "baselines" / "roberta-tuned.json"
RUNS = PROCESSED / "roberta_search.jsonl"  # one line per finished run: an interrupted search picks up from here
WEIGHTS = PROCESSED / "roberta-tuned"  # the five final readers, half precision (git-ignored)
BASE = {"batch": 16, "epochs": 10, "warmup": 0.1, "weight_decay": 0.01, "llrd": 1.0, "max_length": 256}
GRID = [{"backbone": "FacebookAI/roberta-base", "lr": lr} for lr in (1e-5, 2e-5, 3e-5, 5e-5)] + [
    {"backbone": "FacebookAI/roberta-large", "lr": lr} for lr in (5e-6, 1e-5, 2e-5)
]
REFINE = [{"llrd": 0.9}, {"batch": 32}]  # each tried on the best setting of the grid
FOLDS = 5
SEEDS = (0, 1, 2, 3, 4)
MICRO = 16  # sentences per forward pass: a batch of 32 is two of 16 added up (RoBERTa-large at 32 fills 24 GB)
LABELS = {0: "dovish", 1: "hawkish", 2: "neutral"}  # the dataset's coding


def _digest(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]


def batches(lengths, size: int, rng, group: int = 20) -> list[np.ndarray]:
    """Shuffled batches of sentences of similar length (less padding): shuffle, sort within chunks of `group`
    batches, cut, then shuffle the batches."""
    lengths = np.asarray(lengths)
    idx = rng.permutation(len(lengths))
    out = []
    for i in range(0, len(idx), size * group):
        chunk = idx[i : i + size * group]
        chunk = chunk[np.argsort(-lengths[chunk], kind="stable")]
        out += [chunk[j : j + size] for j in range(0, len(chunk), size)]
    return [out[k] for k in rng.permutation(len(out))]


def class_weights(y) -> np.ndarray:
    """n / (classes x n_c): scikit-learn's "balanced"."""
    return len(y) / (3 * np.bincount(y, minlength=3))


def best_epoch(folds: list[list[float]]) -> tuple[int, float]:
    """The epoch (counted from 1) with the highest validation macro-F1 averaged over the folds, and that average."""
    mean = np.mean(folds, axis=0)
    k = int(np.argmax(mean))
    return k + 1, float(mean[k])


def summarize(runs: list[dict]) -> list[dict]:
    """One row per setting with every fold finished: its curve, best epoch and score, in the order first tried."""
    by = {}
    for r in runs:
        by.setdefault(json.dumps(r["config"], sort_keys=True), []).append(r)
    rows = []
    for key, rs in by.items():
        if len(rs) < FOLDS:
            continue
        curves = [r["f1"] for r in sorted(rs, key=lambda r: r["fold"])]
        epoch, f1 = best_epoch(curves)
        rows.append(
            {
                "config": json.loads(key),
                "folds": [[round(x, 4) for x in c] for c in curves],
                "mean_by_epoch": [round(float(x), 4) for x in np.mean(curves, axis=0)],
                "best_epoch": epoch,
                "cv_macro_f1": round(f1, 4),
                "fold_sd": round(float(np.std([c[epoch - 1] for c in curves], ddof=1)), 4),
                "minutes": round(sum(r["minutes"] for r in rs), 1),
            }
        )
    return rows


def _probs(net, tok, texts: list[str], max_length: int = 256, batch: int = 64) -> np.ndarray:
    """P(dovish), P(hawkish), P(neutral) per sentence, read in order of length."""
    import torch

    out = np.zeros((len(texts), 3), dtype=np.float32)
    order = np.argsort([len(t) for t in texts], kind="stable")
    net.eval()
    with torch.no_grad():
        for i in range(0, len(order), batch):
            b = order[i : i + batch]
            enc = tok(
                [texts[j] for j in b], padding=True, truncation=True, max_length=max_length, return_tensors="pt"
            ).to(net.device)
            out[b] = torch.softmax(net(**enc).logits.float(), dim=-1).cpu().numpy()
    return out


class Tuner:
    """Fits and applies RoBERTa readers; needs PyTorch and transformers."""

    def __init__(self, log=print):
        import torch
        import transformers
        from huggingface_hub import model_info

        transformers.logging.set_verbosity_error()  # the load report on every run: the head is new, as it should be
        transformers.logging.disable_progress_bar()
        self.torch, self.log = torch, log
        self.device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.revisions = {b: model_info(b).sha for b in {c["backbone"] for c in GRID}}
        self._tok = {}

    def tok(self, backbone: str):
        from transformers import AutoTokenizer

        if backbone not in self._tok:
            self._tok[backbone] = AutoTokenizer.from_pretrained(backbone, revision=self.revisions[backbone])
        return self._tok[backbone]

    def _optimizer(self, net, cfg: dict, steps: int):
        """AdamW with RoBERTa's betas; no decay on biases and LayerNorm; the learning rate shrinks by cfg['llrd']
        per layer below the head; linear warmup, then linear decay to zero."""
        torch, layers = self.torch, net.config.num_hidden_layers
        groups = {}
        for name, p in net.named_parameters():
            if ".encoder.layer." in name:
                depth = int(name.split(".encoder.layer.")[1].split(".")[0]) + 1
            elif ".embeddings." in name:
                depth = 0
            else:  # the classification head
                depth = layers + 1
            plain = name.endswith("bias") or "LayerNorm" in name
            groups.setdefault((depth, plain), []).append(p)
        params = [
            {
                "params": ps,
                "lr": cfg["lr"] * cfg["llrd"] ** (layers + 1 - depth),
                "weight_decay": 0.0 if plain else cfg["weight_decay"],
            }
            for (depth, plain), ps in groups.items()
        ]
        fused = self.device in ("mps", "cuda")
        opt = torch.optim.AdamW(params, lr=cfg["lr"], betas=(0.9, 0.98), eps=1e-6, fused=fused)
        warm = int(cfg["warmup"] * steps)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: s / max(1, warm) if s < warm else max(0.0, (steps - s) / max(1, steps - warm))
        )
        return opt, sched

    def fit(self, cfg: dict, texts: list[str], y: np.ndarray, seed: int, stop: int | None = None, val=None):
        """Train on (texts, y) along cfg's schedule, stopping after `stop` epochs (all of them by default); with
        `val` = (texts, labels), the validation macro-F1 after each epoch."""
        from transformers import AutoModelForSequenceClassification

        torch = self.torch
        torch.manual_seed(seed)
        net = AutoModelForSequenceClassification.from_pretrained(
            cfg["backbone"],
            revision=self.revisions[cfg["backbone"]],
            num_labels=3,
            id2label=LABELS,
            label2id={v: k for k, v in LABELS.items()},
        ).to(self.device)
        grads = torch.zeros(sum(p.numel() for p in net.parameters()), device=self.device)
        start = 0
        for p in net.parameters():  # every gradient a view of one buffer: clipping takes two operations, not hundreds
            p.grad = grads[start : start + p.numel()].view_as(p)
            start += p.numel()
        tok = self.tok(cfg["backbone"])
        lengths = [len(ids) for ids in tok(texts)["input_ids"]]
        per_epoch = math.ceil(len(texts) / cfg["batch"])
        opt, sched = self._optimizer(net, cfg, per_epoch * cfg["epochs"])
        weight = torch.tensor(class_weights(y), dtype=torch.float32, device=self.device)
        rng, f1 = np.random.default_rng(seed), []
        for _ in range(stop or cfg["epochs"]):
            net.train()
            for b in batches(lengths, cfg["batch"], rng):
                total = weight[torch.as_tensor(y[b], device=self.device)].sum()  # the class-weighted mean's divisor
                for part in np.array_split(b, math.ceil(len(b) / MICRO)):  # larger batches add up parts of MICRO
                    enc = tok(
                        [texts[i] for i in part],
                        padding=True,
                        truncation=True,
                        max_length=cfg["max_length"],
                        return_tensors="pt",
                    ).to(self.device)
                    target = torch.as_tensor(y[part], device=self.device)
                    logits = net(**enc).logits
                    loss = torch.nn.functional.cross_entropy(logits, target, weight=weight, reduction="sum") / total
                    loss.backward()
                norm = torch.dot(grads, grads).sqrt()  # the global norm (vector_norm is far slower on MPS)
                grads.mul_(torch.clamp(1.0 / (norm + 1e-6), max=1.0))  # clipped to 1, as clip_grad_norm_ would
                opt.step()
                sched.step()
                grads.zero_()
            if val is not None:
                f1.append(macro_f1(val[1], self.probs(net, cfg, val[0]).argmax(1)))
        return net, f1

    def probs(self, net, cfg: dict, texts: list[str]) -> np.ndarray:
        return _probs(net, self.tok(cfg["backbone"]), texts, cfg["max_length"])

    def release(self, net):
        net.zero_grad(set_to_none=True)
        del net
        if self.device == "mps":
            self.torch.mps.empty_cache()


def _done() -> list[dict]:
    return [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()] if RUNS.exists() else []


def search(t: Tuner, texts: list[str], y: np.ndarray) -> list[dict]:
    """Every setting of the grid, then each refinement of the best, on the five folds; finished runs are skipped."""
    from sklearn.model_selection import StratifiedKFold

    folds = list(StratifiedKFold(FOLDS).split(texts, y))  # what GridSearchCV(cv=5) used for the TF-IDF baseline
    data = _digest(texts)

    def run_all(cfg: dict):
        for k, (tr, va) in enumerate(folds):
            have = [r for r in _done() if r["config"] == cfg and r["fold"] == k and r["data"] == data]
            if have:
                continue
            start = time.time()
            net, f1 = t.fit(cfg, [texts[i] for i in tr], y[tr], seed=k, val=([texts[i] for i in va], y[va]))
            t.release(net)
            run = {"config": cfg, "fold": k, "seed": k, "data": data, "f1": f1, "minutes": (time.time() - start) / 60}
            with RUNS.open("a") as f:
                f.write(json.dumps(run) + "\n")
            t.log(
                f"{cfg['backbone'].split('/')[1]} {_short(cfg)} fold {k}: best F1 {max(f1):.3f} "
                f"(epoch {int(np.argmax(f1)) + 1}), {run['minutes']:.1f} min"
            )

    grid = [{**BASE, **g} for g in GRID]
    for cfg in grid:
        run_all(cfg)
    rows = [r for r in summarize([r for r in _done() if r["data"] == data]) if r["config"] in grid]
    top = max(rows, key=lambda r: r["cv_macro_f1"])["config"]  # the grid's best, even when resuming later
    for change in REFINE:
        run_all({**top, **change})
    return summarize([r for r in _done() if r["data"] == data])


def _short(cfg: dict) -> str:
    extra = [f"{k} {cfg[k]}" for k in ("llrd", "batch") if cfg[k] != BASE[k]]
    return ", ".join([f"lr {cfg['lr']:g}", *extra])


def run(log=print) -> dict:
    """The search, the final five-seed reader, its labels for the test split and its document scores."""
    import torch
    import transformers

    from . import collect, supervised
    from .llm.scorer import texts_for
    from .textutil import sentences

    RUNS.parent.mkdir(parents=True, exist_ok=True)
    t = Tuner(log)
    train = supervised.load_tdw("train")
    texts, y = train["sentence"].tolist(), train["label"].to_numpy()
    table = search(t, texts, y)
    chosen = max(table, key=lambda r: r["cv_macro_f1"])
    cfg, stop = chosen["config"], chosen["best_epoch"]
    log(f"chosen: {cfg['backbone']} {_short(cfg)}, epoch {stop}, CV macro-F1 {chosen['cv_macro_f1']:.3f}")

    test = supervised.load_tdw("test")["sentence"].tolist()
    docs = collect.usable()
    doc_texts = texts_for(docs)
    per_doc = {d: sentences(doc_texts[d]) for d in docs["doc_id"]}
    flat = [s for d in per_doc for s in per_doc[d]]
    p_test, p_docs, seeds = [], [], []
    for seed in SEEDS:
        start = time.time()
        net, _ = t.fit(cfg, texts, y, seed=seed, stop=stop)
        p_test.append(t.probs(net, cfg, test))
        p_docs.append(t.probs(net, cfg, flat))
        out = WEIGHTS / f"seed-{seed}"
        net.zero_grad(set_to_none=True)
        net.to(torch.float16).save_pretrained(out)
        t.tok(cfg["backbone"]).save_pretrained(out)
        t.release(net)
        seeds.append({"seed": seed, "minutes": round((time.time() - start) / 60, 1)})
        log(f"final seed {seed}: {seeds[-1]['minutes']} min")
    p, q = np.mean(p_test, axis=0), np.mean(p_docs, axis=0)
    documents, i = {}, 0
    for d, sents in per_doc.items():
        part = q[i : i + len(sents)]
        documents[d] = {
            "score": round(float((part[:, 1] - part[:, 0]).mean()), 6) if len(sents) else 0.0,
            "sentences": len(sents),
        }
        i += len(sents)
    record = {
        "model": f"{cfg['backbone']}, fine-tuned here",
        "name": NAME,
        "revision": t.revisions[cfg["backbone"]],
        "backbones": t.revisions,
        "labels": LABELS,
        "device": t.device,
        "versions": {"torch": torch.__version__, "transformers": transformers.__version__},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "train": {
            "split": "train",
            "n": len(texts),
            "sentences_sha": _digest(texts),
            "classes": np.bincount(y, minlength=3).tolist(),
        },
        "rules": {
            "folds": f"StratifiedKFold({FOLDS}) in file order, as GridSearchCV(cv=5)",
            "score": "macro-F1",
            "loss": "cross-entropy, class-balanced",
            "optimizer": "AdamW, betas (0.9, 0.98), eps 1e-6",
            "schedule": "10% linear warmup, then linear decay to zero",
            "grad_clip": 1.0,
            "batches": f"shuffled, grouped by length; larger batches add up the gradients of parts of {MICRO}",
        },
        "search": table,
        "chosen": {"config": cfg, "epoch": stop, "cv_macro_f1": chosen["cv_macro_f1"]},
        "final": {
            "seeds": seeds,
            "combine": "mean of the five seeds' probabilities",
            "weights": str(WEIGHTS.relative_to(ROOT) if WEIGHTS.is_relative_to(ROOT) else WEIGHTS),
        },
        "tdw_test": {
            "sentences_sha": _digest(test),
            "labels": p.argmax(1).tolist(),
            "probs": np.round(p, 5).tolist(),
            "seed_labels": [x.argmax(1).tolist() for x in p_test],
        },
        "documents": documents,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1))
    return record


def saved_probs(texts: list[str]) -> np.ndarray:
    """The saved readers' mean probabilities (weights stored in half precision, read back in full)."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    dirs = sorted(WEIGHTS.glob("seed-*"))
    if not dirs:
        raise SystemExit("No saved readers: run `fomc finetune` first")
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    out = []
    for d in dirs:
        net = AutoModelForSequenceClassification.from_pretrained(d, dtype=torch.float32).to(device)
        out.append(_probs(net, AutoTokenizer.from_pretrained(d), texts))
        del net
    return np.mean(out, axis=0)


def label_team(con) -> int:
    """Add the saved readers' labels for the team's post-cutoff sentences to the record."""
    from . import db, roberta

    sents = db.query(con, "SELECT sentence FROM label_items ORDER BY item_id")["sentence"].tolist()
    if not sents or not OUT.exists():
        return 0
    rec = json.loads(OUT.read_text())
    labels = saved_probs(sents).argmax(1)
    rec["team"] = {"labels": {roberta.sentence_key(s): int(c) for s, c in zip(sents, labels)}}
    OUT.write_text(json.dumps(rec, indent=1))
    return len(sents)
