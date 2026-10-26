"""Sizing identities, downside direction and hostile API inputs; no model calls."""

import math

import pytest
from fastapi.testclient import TestClient

from fomc.duration import ScenarioIn, assumptions, scenario

CFG = {"long_etf": "IEF", "short_etf": "SHY", "durations": {"IEF": 7.1, "SHY": 1.9}}


def test_sizing_dv01_and_cost_identity():
    r = scenario(ScenarioIn(), CFG)
    assert r["target_duration"] == 5
    assert r["dv01_before_usd"] == 600
    assert r["dv01_active_usd"] == -100
    assert r["dv01_after_usd"] == 500
    assert r["legs"][0]["action"] == "sell" and r["legs"][1]["action"] == "buy"
    assert r["legs"][0]["signed_notional_usd"] == -192307.69
    assert r["legs"][1]["signed_notional_usd"] == 192307.69
    assert r["sizing"] == "manual" and r["traded_notional_usd"] == 769230.77  # two legs, in and out
    assert r["cost_usd"] == 76.92
    assert r["selected"]["base_pnl_usd"] == -30000
    assert r["selected"]["portfolio_pnl_after_cost_usd"] == -25076.92
    assert r["selected"]["active_pnl_after_cost_usd"] == 4923.08
    assert r["breakeven_shock_bp"] == pytest.approx(0.7692307692)


def test_a_documents_rule_scales_with_the_budget_as_in_the_backtest():
    """theta * budget, never only capped by it; a manual change is the one the budget caps."""
    for budget, applied in ((2, 1.526), (0.5, 0.3815), (1, 0.763)):
        r = scenario(ScenarioIn(signal_theta=0.763, duration_budget=budget, duration_change=-5), CFG)
        assert r["sizing"] == "rule" and not r["budget_capped"]
        assert r["applied_duration_change"] == pytest.approx(applied)
        assert r["dv01_active_usd"] == pytest.approx(1e6 * applied / 1e4, abs=0.01)
    manual = scenario(ScenarioIn(duration_change=2, duration_budget=0.5), CFG)
    assert manual["sizing"] == "manual" and manual["budget_capped"] and manual["applied_duration_change"] == 0.5


def test_the_round_trip_cost_is_what_the_backtest_charges_one_isolated_signal():
    import pandas as pd

    from fomc.config import settings
    from fomc.evaluate import backtest

    cfg = settings()["backtest"]
    theta, nav = -0.6, 1e6
    days = pd.bdate_range("2024-01-01", periods=12)
    flat = pd.DataFrame({cfg["long_etf"]: 100.0, cfg["short_etf"]: 100.0}, index=days)  # prices still: cost only
    pos = pd.Series(0.0, index=days)
    pos.iloc[2:7] = theta  # one signal held five days, then closed
    charged = -backtest.overlay(pos, flat).sum() * nav * backtest.tilt_scale()
    r = scenario(
        ScenarioIn(
            nav_usd=nav,
            signal_theta=theta,
            duration_budget=cfg["duration_budget_years"],
            cost_bp_per_side=cfg["cost_bp_per_side"],
        ),
        cfg,
    )
    assert r["cost_usd"] == pytest.approx(charged, abs=0.01)


def test_zero_trade_and_zero_budget_are_real_zeros():
    for args in ({"duration_change": 0}, {"duration_budget": 0}):
        r = scenario(ScenarioIn(**args), CFG)
        assert r["cost_usd"] == r["gross_notional_usd"] == r["dv01_active_usd"] == 0
        assert r["breakeven_shock_bp"] is None
        assert all(leg["action"] == "none" for leg in r["legs"])
        assert r["selected"]["portfolio_pnl_after_cost_usd"] == r["selected"]["base_pnl_usd"]
    flat = scenario(ScenarioIn(shock_bp=0), CFG)
    assert math.copysign(1, flat["selected"]["base_pnl_usd"]) == 1


def test_symmetric_shocks_and_direction_flip():
    short = scenario(ScenarioIn(cost_bp_per_side=0), CFG)
    long = scenario(ScenarioIn(duration_change=1, cost_bp_per_side=0), CFG)
    assert short["dv01_active_usd"] == -long["dv01_active_usd"]
    for r in (short, long):
        by = {x["shock_bp"]: x for x in r["scenarios"]}
        assert by[-50]["portfolio_pnl_after_cost_usd"] == -by[50]["portfolio_pnl_after_cost_usd"]
    assert long["selected"]["active_pnl_after_cost_usd"] == -5000


def test_budget_cap_and_money_scaling():
    base = scenario(ScenarioIn(duration_change=-3, duration_budget=0.5), CFG)
    double = scenario(ScenarioIn(nav_usd=2e6, duration_change=-3, duration_budget=0.5), CFG)
    assert base["budget_capped"] and base["applied_duration_change"] == -0.5
    assert base["target_duration"] == 5.5
    assert double["dv01_after_usd"] == 2 * base["dv01_after_usd"]
    assert double["overlay_weight"] == base["overlay_weight"]
    assert math.isclose(
        double["selected"]["portfolio_pnl_after_cost_usd"],
        2 * base["selected"]["portfolio_pnl_after_cost_usd"],
        abs_tol=0.01,
    )


def test_invalid_duration_assumptions():
    for dl, ds in ((1, 2), (2, 2), (math.nan, 2), (7, -1)):
        with pytest.raises(ValueError):
            assumptions({**CFG, "durations": {"IEF": dl, "SHY": ds}})


def _context_rows():
    import pandas as pd

    rows = []
    for i, day in enumerate(pd.bdate_range("2024-01-01", periods=24)):
        rows.append(
            {
                "doc_id": f"minutes_{i}",
                "doc_type": "minutes",
                "release_date": str(day.date()),
                "release_time_et": "14:00",
                "title": "Meeting minutes",
                "speaker": None,
                "url": "https://www.federalreserve.gov/",
                "avail_ts": day.isoformat() + "-05:00",
                "etf_entry": str(day.date()),
                "etf_entry_next": str((day + pd.offsets.BDay()).date()),
                "score": i / 30,
                "relevance": "high",
            }
        )
    return pd.DataFrame(rows)


def test_document_link_is_prior_only_and_matches_frozen_signal_formula():
    from fomc.duration import document_context
    from fomc.evaluate import backtest

    frame = _context_rows()
    cfg = {"zscore_min_events": 12, "duration_budget_years": 1}
    primary = {
        "run_id": "primary",
        "method": "reader",
        "doc_types": "minutes+speech",
        "entry": "etf_entry_next",
        "hold": 5,
    }
    result = document_context(frame, "minutes_18", cfg, primary)
    assert result["eligible"] and result["history_n"] == 18
    expected = backtest.signals(frame.drop(columns="score"), frame[["doc_id", "score"]], ["minutes"], "etf_entry_next")
    original = expected[expected.doc_id == "minutes_18"].iloc[0]
    assert result["theta"] == pytest.approx(original.theta)
    future = frame.copy()
    future.loc[future.doc_id.isin([f"minutes_{i}" for i in range(19, 24)]), "score"] = -100
    unchanged = document_context(future, "minutes_18", cfg, primary)
    assert unchanged["theta"] == result["theta"] and unchanged["history_mean"] == result["history_mean"]
    assert result["entry_date"] == frame.iloc[18].etf_entry_next


PRIMARY = {"run_id": "primary", "method": "reader", "doc_types": "minutes+speech", "entry": "etf_entry_next", "hold": 5}
RULE = {"zscore_min_events": 12, "duration_budget_years": 1}


def test_history_is_the_same_type_with_an_entry_close_as_in_the_backtest():
    from fomc.duration import document_context
    from fomc.evaluate import backtest

    frame = _context_rows()
    frame.loc[frame.index % 3 == 1, "doc_type"] = "speech"  # interleave another type
    frame.loc[0, "etf_entry_next"] = None  # the backtest drops a document without an entry close
    result = document_context(frame, "minutes_21", RULE, PRIMARY)
    minutes = frame[(frame.doc_type == "minutes") & frame.etf_entry_next.notna()]
    assert result["history_n"] == int((minutes.index < 21).sum())
    expected = backtest.signals(
        frame.drop(columns="score"), frame[["doc_id", "score"]], ["minutes", "speech"], "etf_entry_next"
    )
    assert result["z"] == pytest.approx(expected.set_index("doc_id").loc["minutes_21", "z"])


def test_same_minute_releases_are_not_history_and_are_disclosed():
    from fomc.duration import document_context

    frame = _context_rows()
    day = "2024-02-02T"
    frame.loc[20, "avail_ts"] = day + "09:00:00-05:00"
    frame.loc[21, "avail_ts"] = day + "09:00:00-05:00"  # the same minute as minutes_20
    frame.loc[22, "avail_ts"] = day + "14:00:00-05:00"  # later the same day
    frame.loc[23, "avail_ts"] = "2024-02-05T14:00:00-05:00"
    same = document_context(frame, "minutes_21", RULE, PRIMARY)
    assert same["history_n"] == 20 and same["same_time_peers"] == 1 and "same minute" in same["scope"]
    later = document_context(frame, "minutes_22", RULE, PRIMARY)
    assert later["history_n"] == 22 and later["same_time_peers"] == 0  # timestamps, not dates


def test_without_a_document_the_latest_eligible_reading_is_chosen():
    from fomc.duration import document_context

    frame = _context_rows()
    frame.loc[23, "doc_type"] = "statement"  # not a primary type
    frame.loc[22, "relevance"] = "low"
    frame.loc[21, "etf_entry_next"] = None
    assert document_context(frame, None, RULE, PRIMARY)["document"]["doc_id"] == "minutes_20"


def test_document_link_excludes_low_relevance_and_declines_nonprimary_types():
    from fomc.duration import document_context

    frame = _context_rows()
    frame.loc[:2, "relevance"] = "low"
    cfg = {"zscore_min_events": 12, "duration_budget_years": 1}
    primary = {
        "run_id": "primary",
        "method": "reader",
        "doc_types": "minutes+speech",
        "entry": "etf_entry_next",
        "hold": 5,
    }
    assert document_context(frame, "minutes_14", cfg, primary)["history_n"] == 11
    assert not document_context(frame, "minutes_14", cfg, primary)["eligible"]
    frame.loc[18, "doc_type"] = "statement"
    result = document_context(frame, "minutes_18", cfg, primary)
    assert not result["eligible"] and result["duration_change_years"] is None
    assert "not this document type" in result["reason"]


@pytest.mark.parametrize("json_encoded", [False, True])
def test_source_badges_distinguish_primary_series_from_actual_fallback(json_encoded):
    import json

    from fomc import db, provenance

    con = db.connect(":memory:")
    db.init(con)
    source = "U.S. Treasury par curve (fallback)"
    con.execute("INSERT INTO meta VALUES ('yield_source',?)", (json.dumps(source) if json_encoded else source,))
    source = {r["id"]: r for r in provenance.sources(con)}
    assert source["treasury"]["detail"] == "Active source"
    assert source["fred"]["detail"] == "Primary series, fallback used"
    assert source["tdw"]["role"] == "Expert labels"
    assert all(s["url"].startswith("https://") for s in source.values())
    con.close()


def test_the_stored_fallback_string_marks_only_treasury_and_dates_only_it():
    from fomc import db, provenance

    con = db.connect(":memory:")
    db.init(con)
    stored = "U.S. Treasury par yield curve (FRED unavailable: HTTP 500 for DGS10)"  # as the market stage writes it
    con.execute("INSERT INTO meta VALUES ('yield_source',?)", (stored,))
    con.execute("INSERT INTO yields (date, t10y) VALUES ('2026-10-20', 4.1)")
    rows = {r["id"]: r for r in provenance.sources(con)}
    assert rows["treasury"]["detail"] == "Active source" and rows["treasury"]["as_of"] == "2026-10-20"
    assert rows["fred"]["detail"] == "Primary series, fallback used" and rows["fred"]["as_of"] is None
    assert "data-chart-center/interest-rates/TextView" in rows["treasury"]["url"]
    con.close()


@pytest.mark.parametrize("raw", [None, "unknown-provider"])
def test_unknown_source_does_not_claim_active_treasury(raw):
    from fomc import db, provenance

    con = db.connect(":memory:")
    db.init(con)
    con.execute("INSERT INTO meta VALUES ('yield_source',?)", (raw,))
    rows = {r["id"]: r for r in provenance.sources(con)}
    assert rows["treasury"]["detail"] != "Active source"
    assert rows["fred"]["detail"] != "Primary series, fallback used"
    con.close()


def _duration_store():
    import json

    from fomc import db

    con = db.connect(":memory:")
    db.init(con)
    for r in _context_rows().itertuples():
        con.execute(
            "INSERT INTO documents (doc_id, doc_type, release_date, release_time_et, title, url) VALUES (?,?,?,?,?,?)",
            (r.doc_id, r.doc_type, r.release_date, r.release_time_et, r.title, r.url),
        )
        con.execute(
            "INSERT INTO events (doc_id, doc_type, avail_ts, etf_entry, etf_entry_next) VALUES (?,?,?,?,?)",
            (r.doc_id, r.doc_type, r.avail_ts, r.etf_entry, r.etf_entry_next),
        )
        con.execute(
            "INSERT INTO scores (method, doc_id, score, details) VALUES ('reader',?,?,?)",
            (r.doc_id, r.score, json.dumps({"policy_relevance": r.relevance})),
        )
    con.execute("UPDATE documents SET note='duplicate' WHERE doc_id='minutes_23'")  # not a usable document
    con.execute(
        "INSERT INTO backtests (run_id, method, doc_types, hold, entry, is_primary) "
        "VALUES ('primary','reader','minutes+speech',5,'etf_entry_next',1)"
    )
    return con


def test_context_and_source_endpoints_read_the_store(monkeypatch):
    from fomc import api

    con = _duration_store()
    monkeypatch.setattr(api, "PUBLIC", True)
    api.app.dependency_overrides[api.get_con] = lambda: con
    try:
        client = TestClient(api.app)
        latest = client.get("/api/duration/context").json()["context"]
        assert latest["document"]["doc_id"] == "minutes_22" and latest["eligible"] and latest["history_n"] == 22
        chosen = client.get("/api/duration/context", params={"doc_id": "minutes_18"}).json()["context"]
        assert chosen["history_n"] == 18 and chosen["run_id"] == "primary" and chosen["hold_days"] == 5
        assert client.get("/api/duration/context", params={"doc_id": "minutes_23"}).status_code == 404
        assert client.get("/api/duration/context", params={"doc_id": "nope"}).status_code == 404
        assert client.get("/api/duration/context", params={"doc_id": "x" * 151}).status_code == 422
        con.execute("UPDATE backtests SET entry='etf_entry_later'")  # never interpolate an unknown column
        assert client.get("/api/duration/context").json() == {
            "context": None,
            "reason": "No frozen primary strategy is stored.",
        }
        sources = client.get("/api/sources").json()
        assert [s["id"] for s in sources["sources"]] == ["fed", "fred", "treasury", "yahoo", "nyfed", "tdw"]
        assert sources["sources"][0]["detail"] == "23 documents"
    finally:
        api.app.dependency_overrides.pop(api.get_con, None)
        con.close()


def test_scenario_api_is_available_in_public_mode_and_has_no_write_path(monkeypatch):
    from fomc import api

    monkeypatch.setattr(api, "PUBLIC", True)
    # A pure scenario calculation should never open a database or call a provider.
    monkeypatch.setattr(api.db, "connect", lambda: pytest.fail("scenario opened the database"))
    client = TestClient(api.app)
    r = client.post("/api/duration/scenario", json={})
    assert r.status_code == 200
    assert r.json()["dv01_after_usd"] == 500


def test_metadata_handles_empty_research_and_unavailable_prices(monkeypatch):
    from fomc import api, db

    con = db.connect(":memory:")
    db.init(con)
    api.app.dependency_overrides[api.get_con] = lambda: con
    try:
        response = TestClient(api.app).get("/api/duration")
        assert response.status_code == 200
        result = response.json()
        assert result["research"] is None and result["market_as_of"] is None
        assert result["assumptions"]["spread_duration"] == pytest.approx(5.2)
        assert result["defaults"]["duration_budget"] == 1
        monkeypatch.setattr(api, "settings", lambda: {"backtest": {**CFG, "durations": {"IEF": 1, "SHY": 1}}})
        assert TestClient(api.app).get("/api/duration").status_code == 503
    finally:
        api.app.dependency_overrides.pop(api.get_con, None)
        con.close()


@pytest.mark.parametrize(
    "body",
    [
        {"nav_usd": 0},
        {"nav_usd": -1},
        {"nav_usd": 1e13},
        {"duration_budget": -1},
        {"base_duration": 31},
        {"shock_bp": 501},
        {"cost_bp_per_side": -1},
        {"nav_usd": "NaN"},
        {"nav_usd": True},
        {"shock_bp": "Infinity"},
        {"unexpected": "field"},
        {"signal_theta": 1.5},
        {"signal_theta": "0.5"},
    ],
)
def test_invalid_scenario_inputs_return_422(body):
    from fomc.api import app

    assert TestClient(app).post("/api/duration/scenario", json=body).status_code == 422


def test_nonstandard_nonfinite_json_reports_validation_instead_of_500():
    from fomc.api import app

    r = TestClient(app).post(
        "/api/duration/scenario", content='{"nav_usd":NaN}', headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "finite_number"


@pytest.mark.parametrize(
    "minimum,valid_count,missing,expected", [(12, 5, 10, False), (20, 18, 0, False), (12, 18, 0, True)]
)
def test_live_tilt_uses_valid_history_configured_minimum_and_years(
    monkeypatch, minimum, valid_count, missing, expected
):
    import pandas as pd

    from fomc import api
    from fomc.llm import scorer

    class OfflineScorer:
        model = "test-reader"

        def __init__(self, **_kwargs):
            pass

        def call(self, _job):
            return {
                "status": "ok",
                "parsed": {"stance_score": 0.7, "policy_relevance": "high"},
                "model_served": self.model,
                "usage": {},
            }

    monkeypatch.setattr(api, "PUBLIC", False)
    monkeypatch.setattr(api.provider, "status", lambda: {"key_configured": True})
    monkeypatch.setattr(scorer, "Scorer", OfflineScorer)
    cfg = {"backtest": {"zscore_min_events": minimum, "duration_budget_years": 2}, "llm": {"prices_per_mtok": {}}}
    monkeypatch.setattr(api, "settings", lambda: cfg)
    values = [i / 20 for i in range(valid_count)] + [float("nan")] * missing
    monkeypatch.setattr(api.db, "query", lambda *_args: pd.DataFrame({"score": values}))
    result = api.live_score(api.ScoreIn(text="policy outlook " * 10, doc_type="speech"), con=None)
    assert result["tilt_min_events"] == minimum
    assert bool(result["tilt"]) == expected
    if expected:
        assert result["tilt"]["history_n"] == valid_count
        assert result["tilt"]["duration_years"] == 2 * result["tilt"]["theta"]
