"""The fine-tuned RoBERTa's bookkeeping: batches, the choice of setting and epoch, and the saved record's use.

None of this needs PyTorch: the training itself runs offline (`fomc finetune`), and the pipeline only reads its
record.
"""

import json

import numpy as np
import pytest

from fomc import finetune, roberta


def test_batches_cover_every_sentence_once_and_group_by_length():
    lengths = np.random.default_rng(1).integers(5, 120, 1003)
    got = finetune.batches(lengths, 16, np.random.default_rng(0))
    flat = np.concatenate(got)
    assert sorted(flat.tolist()) == list(range(1003))
    assert len(got) == int(np.ceil(1003 / 16))  # one schedule step per batch, as the optimizer counts them
    spread = np.mean([np.ptp(lengths[b]) for b in got if len(b) == 16])
    assert spread < 0.5 * np.ptp(lengths)  # similar lengths share a batch: less padding


def test_balanced_weights_match_scikit_learn():
    from sklearn.utils.class_weight import compute_class_weight

    y = np.array([0] * 5 + [1] * 3 + [2] * 12)
    assert finetune.class_weights(y) == pytest.approx(compute_class_weight("balanced", classes=np.arange(3), y=y))


def test_the_setting_and_epoch_are_chosen_on_the_folds_alone():
    base = {**finetune.BASE, "backbone": "FacebookAI/roberta-base", "lr": 2e-5}
    other = {**base, "lr": 5e-5}
    runs = [{"config": base, "fold": k, "f1": [0.50, 0.60, 0.58], "minutes": 1.0} for k in range(finetune.FOLDS)]
    runs += [{"config": other, "fold": k, "f1": [0.55, 0.57, 0.65 + k / 100], "minutes": 1.0} for k in range(4)]
    rows = finetune.summarize(runs)
    assert [r["config"] for r in rows] == [base]  # a setting missing a fold is not a candidate yet
    assert (rows[0]["best_epoch"], rows[0]["cv_macro_f1"]) == (2, 0.6)
    assert finetune.best_epoch([[0.1, 0.3, 0.2], [0.3, 0.1, 0.2]]) == (1, pytest.approx(0.2))


def test_the_pipeline_uses_a_saved_record_only_for_the_sentences_it_read(tmp_path):
    test, team = ["Rates stay put.", "Inflation is too high."], ["A new sentence.", "Another one."]
    rec = {
        "model": "FacebookAI/roberta-large, fine-tuned here",
        "revision": "abc",
        "tdw_test": {"sentences_sha": roberta._digest(test), "labels": [2, 1]},
        "team": {"labels": {roberta.sentence_key(team[0]): 0}},
        "documents": {f"statement_{i}": {"score": i / 10, "sentences": 20} for i in range(12)},
        "chosen": {"config": {"lr": 1e-5}, "epoch": 4, "cv_macro_f1": 0.7},
        "search": [{"config": {"lr": 1e-5}, "best_epoch": 4, "cv_macro_f1": 0.7, "fold_sd": 0.02, "folds": []}],
    }
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(rec))
    assert roberta.test_labels(test, path) == [2, 1]
    assert roberta.test_labels(test[::-1], path) is None  # other sentences: not its labels
    assert roberta.team_labels(team[:1], path) == [0]
    assert roberta.team_labels(team, path) is None  # a sentence it never read
    claude = {f"statement_{i}": -i / 5 for i in range(12)}
    out = roberta.describe(claude, {d: "statement" for d in claude}, path)
    assert out["types"]["statement"] == {"n": 12, "pearson": -1.0, "spearman": -1.0}
    assert out["chosen"]["epoch"] == 4 and "folds" not in out["search"][0]
    assert roberta.describe(claude, {}, tmp_path / "missing.json") == {}
