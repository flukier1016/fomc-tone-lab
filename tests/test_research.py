"""Research layer: policy decisions, redlines, multiple testing, deflated Sharpe, event panels."""

import numpy as np
import pandas as pd

from fomc import policy
from fomc.evaluate import backtest, event_study


def test_target_range_and_action_from_statement_wording():
    hike = (
        "In support of these goals, the Committee decided to raise the target range for the federal funds rate "
        "to 1‑1/2 to 1-3/4 percent."  # the Board's pages mix non-breaking and plain hyphens
    )
    assert policy.parse_statement(hike) == {"action": 1, "range_low": 1.5, "range_high": 1.75}
    cut = (
        "The Committee decided to lower the target range for the federal funds rate by 1/4 percentage point "
        "to 4 to 4-1/4 percent."
    )
    assert policy.parse_statement(cut) == {"action": -1, "range_low": 4.0, "range_high": 4.25}
    zlb = "In determining how long to maintain the current 0 to 1/4 percent target range for the federal funds rate."
    assert (policy.parse_statement(zlb)["range_low"], policy.parse_statement(zlb)["range_high"]) == (0.0, 0.25)
    directive = (
        "The Committee directs the Desk to undertake open market operations as necessary to maintain the "
        "federal funds rate in a target range of 1-3/4 to 2 percent."
    )
    assert policy.parse_statement(directive)["range_high"] is None


def _statement(doc_id, date, text):
    return {"doc_id": doc_id, "meeting_date": date, "release_date": date, "text": text}


def test_decisions_compare_each_statement_with_the_previous_decision():
    base = "the Committee decided to {} the target range for the federal funds rate {} percent."
    st = pd.DataFrame(
        [
            _statement("s1", "2022-03-16", base.format("raise", "to 1/4 to 1/2")),
            _statement("s2", "2022-03-30", "Statement regarding dollar liquidity swap lines."),
            _statement("s3", "2022-05-04", base.format("raise", "to 3/4 to 1")),
            _statement("s4", "2022-06-15", base.format("maintain", "at 3/4 to 1")),
        ]
    )
    d = policy.decisions(st).set_index("doc_id")
    assert d.loc["s1", "action"] == 1 and pd.isna(d.loc["s1", "change_bp"])
    assert pd.isna(d.loc["s2", "action"]) and pd.isna(d.loc["s2", "prev_doc_id"])  # not a decision
    assert d.loc["s3", "change_bp"] == 50 and d.loc["s3", "prev_doc_id"] == "s1"  # skips the swap-line notice
    assert d.loc["s4", "action"] == 0 and d.loc["s4", "change_bp"] == 0


def test_redline_keeps_paragraphs_and_counts_words():
    segments, stats = policy.diff("Rates held.\n\nInflation is high.", "Rates rose.\n\nInflation is high.")
    assert [s["op"] for s in segments] == ["equal", "delete", "insert", "equal"]
    assert stats["words_added"] == 1 and stats["words_removed"] == 1
    assert segments[-1]["text"] == "\n\nInflation is high."


def test_bh_qvalues_match_statsmodels():
    from statsmodels.stats.multitest import multipletests

    p = pd.Series([0.001, 0.02, 0.03, 0.2, 0.5, np.nan], index=list("abcdef"))
    q = event_study.bh_qvalues(p)
    assert np.allclose(q.dropna().to_numpy(), multipletests(p.dropna(), method="fdr_bh")[1])
    assert np.isnan(q["f"])


def test_probabilistic_and_deflated_sharpe():
    rng = np.random.default_rng(0)
    skill = pd.Series(rng.normal(0.0008, 0.01, 2500))
    noise = pd.Series(rng.normal(0.0, 0.01, 2500))
    assert backtest.probabilistic_sharpe(skill) > 0.95 > backtest.probabilistic_sharpe(noise)
    sharpes = rng.normal(0, 0.02, 40)
    assert backtest.expected_max_sharpe(sharpes, 40) > backtest.expected_max_sharpe(sharpes, 5) > 0
    assert backtest.expected_max_sharpe(sharpes[:1]) == 0.0  # a single pre-registered test needs no deflation
    assert backtest.probabilistic_sharpe(skill, 0.03) < backtest.probabilistic_sharpe(skill)


def test_event_panel_groups_controls_and_response_curves():
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2015-01-01", periods=420)
    n = 60
    at = np.linspace(12, 380, n).astype(int)
    tone = rng.normal(size=n)
    moves = {t: rng.normal(0, 0.03, len(days)) for t in ("3 Mo", "2 Yr", "5 Yr", "10 Yr", "30 Yr")}
    moves["2 Yr"][at] += 0.05 * tone  # the 2-year reacts to tone on release days
    yields = pd.DataFrame({t: 2 + np.cumsum(m) for t, m in moves.items()}, index=days)
    events = pd.DataFrame(
        {
            "doc_id": [f"speech_{i}" for i in range(n)],
            "doc_type": "speech",
            "ust_pre": days[at - 1],
            "ust_post": days[at],
            "speaker_role": ["Chair" if i % 3 == 0 else "Governor" for i in range(n)],
        }
    )
    scores = {"m": pd.DataFrame({"doc_id": events["doc_id"], "score": tone})}
    panel = event_study.build_panel(events, yields, scores)
    assert set(panel["group"]) == {"speech", "speech_chair", "speech_other"}
    res = event_study.regress(panel, ["m"])
    main = res[(res["doc_type"] == "speech") & (res["regressor"] == "level") & (res["outcome"] == "d2y")]
    base = main[(main["sample"] == "all") & (main["control"] == "none")].iloc[0]
    assert base["t"] > 5 and base["q_bh"] < 0.01
    assert {"none", "d3m"} <= set(main["control"]) and "decision" not in set(main["control"])  # speeches only
    assert res.loc[res["control"] != "none", "q_bh"].isna().all()  # q-values only on the main grid
    assert res.loc[res["doc_type"].isin(["speech_chair", "speech_other"]), "q_bh"].isna().all()  # subsets: outside
    curves = event_study.response_curves(events, yields, panel, ["m"])
    speech = curves[(curves["doc_type"] == "speech") & (curves["regressor"] == "level")]
    assert set(speech["bucket"]) == {"dovish", "middle", "hawkish"} and speech["day"].between(-5, 20).all()
    day0 = speech[speech["day"] == 0].set_index("bucket")["mean_bp"]
    assert day0["hawkish"] > day0["dovish"]


def test_shifts_skip_unscored_documents_and_notices_and_statements_get_presser_checks():
    rng = np.random.default_rng(5)
    days = pd.bdate_range("2016-01-01", periods=420)
    n = 40
    at = np.linspace(10, 400, n).astype(int)
    dates = days[at]
    yields = pd.DataFrame(
        {t: 2 + np.cumsum(rng.normal(0, 0.03, len(days))) for t in event_study.TENORS.values()}, index=days
    )
    ids = [f"statement_{d:%Y%m%d}" for d in dates]
    pressers = [f"presser_{d:%Y%m%d}" for i, d in enumerate(dates) if i % 2 == 0]
    events = pd.concat(
        [
            pd.DataFrame({"doc_id": ids, "doc_type": "statement", "ust_pre": days[at - 1], "ust_post": dates}),
            pd.DataFrame(
                {"doc_id": pressers, "doc_type": "presser", "ust_pre": days[at[::2] - 1], "ust_post": days[at[::2] + 1]}
            ),
        ]
    )
    notices = {ids[5], ids[17]}  # a swap-line notice and a framework review: not decisions
    decisions = pd.DataFrame(
        {
            "doc_id": [i for i in ids if i not in notices],
            "meeting_date": [d for i, d in zip(ids, dates) if i not in notices],
        }
    ).assign(change_bp=0.0)
    every = pd.DataFrame({"doc_id": ids + pressers, "score": rng.normal(size=len(ids) + len(pressers))})
    scores = {
        "m": every,
        "supervised": every.assign(score=rng.normal(size=len(every))),
        "llm:x": every[every["doc_id"] != ids[10]],  # Claude left one decision out (low policy relevance)
    }
    panel = event_study.build_panel(events, yields, scores, decisions)
    st = panel[panel["group"] == "statement"]
    assert st["m__shift"].notna().sum() == n - len(notices) - 1  # decision against decision only
    assert st.loc[st["doc_id"].isin(notices), "m__shift"].isna().all()
    assert st["llm:x__shift"].notna().sum() == n - len(notices) - 2  # one gap, not two
    res = event_study.regress(panel, list(scores))
    lvl = res[(res["doc_type"] == "statement") & (res["method"] == "m") & (res["regressor"] == "level")]
    assert "no_presser" in set(lvl["sample"]) and "presser" in set(lvl["control"])
    assert "baseline" in set(res.loc[res["method"] == "llm:x", "control"])
    assert "baseline" not in set(res.loc[res["method"] == "m", "control"])


def test_agreement_metrics_match_scikit_learn():
    from sklearn.metrics import cohen_kappa_score, f1_score

    from fomc import labels

    rng = np.random.default_rng(3)
    for _ in range(20):
        a, b = rng.integers(-1, 2, 40), rng.integers(-1, 2, 40)
        assert np.isclose(labels.cohen_kappa(a, b), cohen_kappa_score(a, b))
        assert np.isclose(labels.macro_f1(a, b), f1_score(a, b, average="macro"))
    assert labels.cohen_kappa([1, 1], [1, 1]) == 1.0


def test_hosted_runtime_never_imports_the_research_stack():
    """The hosted image installs requirements-serve.txt only; every module the API imports, including the Story
    endpoint's lazy imports, must run without the research stack, the embedding model or python-pptx."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "class Block:\n"
        "    blocked = {'sklearn', 'statsmodels', 'scipy', 'matplotlib', 'requests', 'pypdf', 'yfinance',\n"
        "               'fastembed', 'onnxruntime', 'pptx'}\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in self.blocked:\n"
        "            raise ImportError('not in the serve image: ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import fomc.api, fomc.fed, fomc.labels, fomc.policy, fomc.store, fomc.story, fomc.story_technical\n"
        "import fomc.llm.scorer\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_dissents_and_reserve_bank_titles_are_read_from_the_text():
    from fomc import fed

    st = pd.DataFrame(
        [
            {
                "doc_id": "statement_20260729",
                "release_date": "2026-07-29",
                "text": "Voting against the monetary policy action were Beth M. Hammack, Neel Kashkari, and Lorie K. "
                "Logan, who preferred to raise the target range for the federal funds rate by 1/4 percentage point.",
            },
            {
                "doc_id": "statement_20241218",
                "release_date": "2024-12-18",
                "text": "Voting against the action was Beth M. Hammack, who preferred to maintain the target range.",
            },
            {  # two groups in one sentence, and the sentence on absences after it
                "doc_id": "statement_20251210",
                "release_date": "2025-12-10",
                "text": "Voting against this action were Stephen I. Miran, who preferred to lower the target range by "
                "1/2 percentage point at this meeting; and Austan D. Goolsbee and Jeffrey R. Schmid, who preferred no "
                "change to the target range at this meeting. Absent and not voting was Adriana D. Kugler.",
            },
        ]
    )
    d = fed.dissents(st)
    assert list(d["name"]) == [
        "Beth M. Hammack", "Neel Kashkari", "Lorie K. Logan", "Beth M. Hammack",
        "Stephen I. Miran", "Austan D. Goolsbee", "Jeffrey R. Schmid",
    ]  # fmt: skip
    assert list(d["preferred"]) == ["hike", "hike", "hike", "hold", "cut", "hold", "hold"]
    assert d["reason"].iloc[-1] == "preferred no change to the target range at this meeting"
    banks = fed._banks(
        [
            "Lorie K. Logan, President of the Federal Reserve Bank of Dallas, with Raphael W. Bostic, President "
            "of the Federal Reserve Bank of Atlanta, as alternate;",
            "Cheryl L. Venable, First Vice President, Federal Reserve Bank of Atlanta",
            "Susan M. Collins, Alberto G. Musalem, and Jeffrey R. Schmid, Presidents of the Federal Reserve Banks "
            "of Boston, St. Louis, and Kansas City, respectively",
        ]
    )
    assert banks["Lorie K. Logan"] == ("President", "Dallas") and banks["Raphael W. Bostic"][1] == "Atlanta"
    assert banks["Cheryl L. Venable"] == ("First Vice President", "Atlanta")
    assert banks["Alberto G. Musalem"][1] == "St. Louis" and banks["Jeffrey R. Schmid"][1] == "Kansas City"


def test_fred_csv_parsing_and_fallback_to_the_treasury(monkeypatch, tmp_path):
    import pytest

    from fomc import market

    new = b"observation_date,DGS2\n2026-10-14,3.57\n2026-10-15,.\n2026-10-16,3.60\n"
    old = b"DATE,DGS2\n2026-10-14,3.57\n"
    s = market.parse_fred(new, "DGS2")
    assert list(s.dropna()) == [3.57, 3.60] and s.isna().sum() == 1  # "." is a missing quote
    assert market.parse_fred(old, "DGS2").iloc[0] == 3.57
    with pytest.raises(ValueError):
        market.parse_fred(b"<!doctype html><title>Site Maintenance</title>", "DGS2")

    monkeypatch.setattr(market, "PROCESSED", tmp_path)
    monkeypatch.setattr(market, "ensure_dirs", lambda: None)
    monkeypatch.setattr(market, "fred_yields", lambda start: (_ for _ in ()).throw(ValueError("maintenance")))
    curve = pd.DataFrame({"2 Yr": [3.5]}, index=pd.DatetimeIndex(["2026-10-16"], name="Date"))
    monkeypatch.setattr(market, "treasury_yields", lambda start_year: curve)
    monkeypatch.setattr(market, "etf_prices", lambda start: pd.DataFrame({"SHY": [1.0]}))
    source = market.build()
    assert source.startswith("U.S. Treasury") and "maintenance" in source
    assert (tmp_path / "yield_source.txt").read_text() == source


class _FakeEncoder:
    """Bag-of-keywords vectors: enough to separate hawkish, dovish and neutral toy sentences."""

    words = ("raise", "tighten", "inflation", "lower", "ease", "weak", "growth", "the")

    def __init__(self):
        self.calls = 0

    def embed(self, texts, batch_size=256):
        self.calls += 1
        for t in texts:
            toks = t.lower().replace(".", " ").split()
            yield np.array([toks.count(w) for w in self.words], dtype=np.float32)


def test_sentence_embedding_baseline_trains_scores_and_caches(monkeypatch, tmp_path):
    from fomc import embeddings

    monkeypatch.setattr(embeddings, "CACHE", tmp_path / "cache.csv")
    monkeypatch.setattr(embeddings, "PROCESSED", tmp_path)
    hawk = [f"We will raise rates and tighten policy as inflation rises {i}." for i in range(12)]
    dove = [f"We will lower rates and ease policy as growth is weak {i}." for i in range(12)]
    neutral = [f"The meeting took place in the building number {i}." for i in range(12)]
    data = pd.DataFrame({"sentence": hawk + dove + neutral, "label": [1] * 12 + [0] * 12 + [2] * 12})
    enc = _FakeEncoder()
    model = embeddings.SentenceEmbeddings(enc).train(data)
    assert list(model.predict(["They will raise rates to tighten policy.", "They will ease and lower rates."])) == [
        1,
        0,
    ]
    docs = pd.DataFrame({"doc_id": ["h", "d"]})
    texts = {"h": "We raise rates. We tighten policy again.", "d": "We lower rates. We ease policy again."}
    first = model.score_documents(docs, texts).set_index("doc_id")["score"]
    assert first["h"] > 0 > first["d"]
    calls = enc.calls
    again = model.score_documents(docs, texts).set_index("doc_id")["score"]
    assert enc.calls == calls and np.allclose(again, first)  # unchanged texts come from the cache


def test_evidence_spans_point_into_the_source_text():
    from fomc.llm.scorer import verify_quotes

    src = "Inflation “remains elevated”--for now.\n\nThe Committee  will   act."
    out = verify_quotes(['remains elevated"--for now', "the committee will act", "never said"], src)
    assert out["verified"] == 2 and out["unverified"] == ["never said"]
    a, b = out["spans"]
    assert src[a["start"] : a["end"]] == "remains elevated”--for now"
    assert src[b["start"] : b["end"]] == "The Committee  will   act"


def test_tone_shift_signal_and_duration_scaling():
    events = pd.DataFrame(
        {
            "doc_id": ["s1", "s2", "s3", "m1", "m2"],
            "doc_type": ["statement"] * 3 + ["minutes"] * 2,
            "avail_ts": pd.to_datetime(["2024-01-31", "2024-03-20", "2024-05-01", "2024-02-21", "2024-04-10"]),
        }
    )
    scores = pd.DataFrame({"doc_id": ["s1", "s2", "s3", "m1", "m2"], "score": [0.1, 0.4, 0.2, -0.2, 0.3]})
    shift = backtest.shift_scores(scores, events).set_index("doc_id")["score"]
    assert np.allclose([shift["s2"], shift["s3"], shift["m2"]], [0.3, -0.2, 0.5]) and "s1" not in shift
    assert np.isclose(backtest.tilt_scale(), 1.0 / (7.1 - 1.9))  # one year of duration per unit budget


def test_paired_tests_separate_a_real_lead_from_noise():
    from fomc.evaluate.validity import compare

    rng = np.random.default_rng(0)
    truth = rng.integers(0, 3, 400)
    good = np.where(rng.random(400) < 0.85, truth, (truth + 1) % 3)
    weak = np.where(rng.random(400) < 0.55, truth, (truth + 2) % 3)
    lead = compare(truth, {"llm:x": good, "weak": weak}, "llm:x", n_boot=500)[0]
    assert lead["method"] == "weak" and lead["f1_diff"] > 0.2 and lead["ci_low"] > 0
    assert lead["p_boot"] < 0.01 and lead["mcnemar_p"] < 0.01 and lead["only_target_right"] > lead["only_other_right"]
    tie = compare(truth, {"llm:x": good, "same": good.copy()}, "llm:x", n_boot=200)[0]
    assert tie["f1_diff"] == 0 and tie["mcnemar_p"] == 1.0 and tie["only_target_right"] == tie["only_other_right"] == 0


def test_stability_compares_the_main_run_with_a_repeat(tmp_path, monkeypatch):
    import json

    from fomc import audit
    from fomc.llm import rubric, scorer

    monkeypatch.setattr(scorer, "LLM_DIR", tmp_path)
    runs = {  # (stance score, overall stance) per document
        "level": [(0.5, 1), (-0.25, 0), (0.0, 0), (0.75, 2)],
        "level_r2": [(0.5, 1), (-0.5, -1), (0.25, 1), (0.75, 2)],
    }
    for mode, values in runs.items():
        root = tmp_path / "m" / rubric.RUBRIC_VERSION / mode
        root.mkdir(parents=True)
        for i, (v, stance) in enumerate(values):
            parsed = {"stance_score": v, "overall_stance": stance, "confidence": 0.8, "policy_relevance": 1}
            parsed.update({d: 0 for d in rubric.DIMENSIONS})
            rec = {
                "key": f"d{i}",
                "status": "ok",
                "parsed": parsed,
                "checks": {"evidence": {"share": 1.0}},
                "model_served": "m",
            }
            (root / f"d{i}.json").write_text(json.dumps(rec))
    r = audit.stability_report("m").iloc[0]
    assert r["n"] == 4 and r["run_tag"] == "r2"
    assert r["overall_stance_agreement"] == 0.5 and r["within_one_step"] == 1.0
    assert np.isclose(r["mean_abs_diff"], 0.125) and r["corr_stance_score"] > 0.9
    assert audit.stability_report("m", "r3").empty
