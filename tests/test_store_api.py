"""SQLite store and REST API, against a throwaway database."""

import sqlite3

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from fomc import db, store


@pytest.fixture()
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    db.init(c)
    docs = pd.DataFrame(
        [
            {
                "doc_id": "minutes_20240131",
                "doc_type": "minutes",
                "release_date": "2024-02-21",
                "release_time_et": "14:00",
                "n_words": 9,
                "note": None,
                "title": None,
                "speaker": None,
                "text": "Participants noted that inflation expectations remained well anchored.",
            },
            {
                "doc_id": "speech_powell1",
                "doc_type": "speech",
                "release_date": "2024-03-01",
                "release_time_et": "10:00",
                "n_words": 8,
                "note": None,
                "title": "Outlook",
                "speaker": "Jerome H. Powell",
                "text": "Labor markets are strong and the economy keeps growing.",
            },
        ]
    )
    db.upsert(c, "documents", docs)
    c.execute("INSERT INTO documents_fts (documents_fts) VALUES ('rebuild')")
    c.commit()
    yield c
    c.close()


def test_full_text_search_uses_external_content(con):
    hits = con.execute(
        "SELECT d.doc_id FROM documents_fts f JOIN documents d ON d.rowid = f.rowid WHERE documents_fts MATCH 'anchor'"
    ).fetchall()  # porter stemming: anchored
    assert [h[0] for h in hits] == ["minutes_20240131"]
    sizes = dict(con.execute("SELECT name, 1 FROM sqlite_master WHERE name LIKE 'documents_fts%'").fetchall())
    assert "documents_fts_content" not in sizes  # no second copy of the text


def test_backtest_curve_roundtrip(con):
    dates = pd.bdate_range("2024-01-01", periods=5)
    db.upsert(
        con,
        "etf_prices",
        pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "SHY": 1.0, "IEI": 1.0, "IEF": 1.0, "TLT": 1.0}),
    )
    ret = pd.Series([0.001, -0.002, 0.0, 0.003, 0.0005], index=dates)
    store.save_backtests(con, pd.DataFrame([{"run_id": "r1", "method": "m"}]), {"r1": ret})
    back = store.load_curve(con, "r1")
    assert list(back.index) == list(dates.strftime("%Y-%m-%d"))
    assert np.allclose(back.to_numpy(), ret.to_numpy(), atol=1e-7)


def test_migration_from_v1_drops_duplicated_storage(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, meeting_date TEXT,
            release_date TEXT, release_time_et TEXT, time_source TEXT, info_start_et TEXT, url TEXT, speaker TEXT,
            speaker_role TEXT, title TEXT, n_words INTEGER, text_sha256 TEXT, note TEXT, text TEXT);
        INSERT INTO documents (doc_id, doc_type, text) VALUES ('d1', 'speech', 'tightening ahead');
        CREATE VIRTUAL TABLE documents_fts USING fts5 (doc_id UNINDEXED, title, speaker, text);
        CREATE TABLE backtest_returns (run_id TEXT, date TEXT, ret REAL, PRIMARY KEY (run_id, date));
    """)
    old.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    c = db.connect()
    db.init(c)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert "backtest_returns" not in names and "backtest_curves" in names
    assert c.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(db.SCHEMA_VERSION)
    assert c.execute("SELECT count(*) FROM documents_fts WHERE documents_fts MATCH 'tighten*'").fetchone()[0] == 1


def test_api_search_and_detail(con):
    from fomc.api import app

    client = TestClient(app)
    r = client.get("/api/documents", params={"q": "inflation anchored"}).json()
    assert r["total"] == 1 and "<mark>" in r["items"][0]["snippet"]
    r = client.get("/api/documents", params={"q": 'labor" OR "x'}).json()  # hostile syntax is quoted, not run
    assert "items" in r
    detail = client.get("/api/documents/speech_powell1").json()
    assert detail["document"]["speaker"] == "Jerome H. Powell"
    assert client.get("/api/documents/nope").status_code == 404
    assert client.post("/api/score", json={"text": "x" * 80, "doc_type": "speech"}).status_code in (400, 502)


@pytest.mark.parametrize(
    "q,expected",
    [
        ("anchored OR growing", {"minutes_20240131", "speech_powell1"}),
        ("anchored OR growing -labor", {"minutes_20240131"}),  # the exclusion applies to the whole OR
        ("anchored OR growing NOT labor", {"minutes_20240131"}),
        ("expect*", {"minutes_20240131"}),
        ("inflation -anchored", set()),  # a real empty result, not a reversed one
        ('"inflation expectations" -labor', {"minutes_20240131"}),
    ],
)
def test_search_keeps_exclusions_and_prefixes(con, q, expected):
    from fomc.api import app

    r = TestClient(app).get("/api/documents", params={"q": q})
    assert r.status_code == 200
    assert {d["doc_id"] for d in r.json()["items"]} == expected


def test_a_search_of_exclusions_alone_is_refused_not_reversed(con):
    from fomc.api import app

    for q in ("-labor", "NOT labor"):
        r = TestClient(app).get("/api/documents", params={"q": q})
        assert r.status_code == 400 and "leave documents out" in r.json()["detail"]


def test_unversioned_static_files_revalidate_and_fingerprinted_ones_stay(con):
    from fomc.api import app

    client = TestClient(app)
    assert client.get("/static/img/fed.jpg").headers["cache-control"] == "no-cache"
    assert "immutable" in client.get("/static/app.js?v=abc").headers["cache-control"]


def test_document_scatter_shares_filters_and_ignores_pagination(con):
    from fomc.api import app

    template = {
        "doc_type": "speech",
        "release_date": "2024-03-02",
        "speaker": "Jerome H. Powell",
        "text": "Labor markets remain strong.",
        "note": None,
    }
    additions = [
        {**template, "doc_id": "speech_powell2"},
        {**template, "doc_id": "speech_later", "release_date": "2024-03-04"},
        {**template, "doc_id": "speech_other", "speaker": "Michelle Bowman"},
        {**template, "doc_id": "minutes_other", "doc_type": "minutes"},
        {**template, "doc_id": "speech_excluded", "note": "under 300 words"},
        {**template, "doc_id": "speech_unmatched", "text": "Inflation expectations are anchored."},
    ]
    db.upsert(con, "documents", pd.DataFrame(additions))
    db.upsert(
        con,
        "scores",
        pd.DataFrame(
            [
                {"doc_id": "speech_powell1", "method": "supervised", "score": 0.3},
                {"doc_id": "speech_powell2", "method": "supervised", "score": -0.4},
                {"doc_id": "speech_powell1", "method": "dictionary", "score": 0.9},
            ]
        ),
    )
    con.execute("INSERT INTO documents_fts (documents_fts) VALUES ('rebuild')")
    con.commit()
    client = TestClient(app)
    params = {
        "q": "labor",
        "types": "speech",
        "speaker": "Powell",
        "start": "2024-03-01",
        "end": "2024-03-02",
        "method": "supervised",
        "limit": 1,
        "offset": 1,
    }
    listed = client.get("/api/documents", params=params).json()
    assert set(listed) == {"total", "method", "items"} and listed["total"] == 2
    assert len(listed["items"]) == 1 and "snippet" in listed["items"][0]
    scattered = client.get("/api/documents", params={**params, "mode": "scatter"}).json()
    assert set(scattered) == {"total", "method", "items", "low_relevance"}
    assert scattered["total"] == 2 and scattered["method"] == "supervised" and scattered["low_relevance"] == 0
    assert scattered["items"] == [
        {"doc_id": "speech_powell1", "doc_type": "speech", "release_date": "2024-03-01", "score": 0.3},
        {"doc_id": "speech_powell2", "doc_type": "speech", "release_date": "2024-03-02", "score": -0.4},
    ]
    assert client.get("/api/documents", params={"mode": "scatter", "q": "unfindable"}).json()["items"] == []
    assert client.get("/api/documents", params={"mode": "unsupported"}).status_code == 422
    # Claude's low-relevance readings stay out of the timeline, as they stay out of the research
    db.upsert(
        con,
        "scores",
        pd.DataFrame(
            [
                {
                    "doc_id": "speech_powell1",
                    "method": "llm:test",
                    "score": 0.0,
                    "details": '{"policy_relevance": "low"}',
                },
                {
                    "doc_id": "speech_powell2",
                    "method": "llm:test",
                    "score": 0.5,
                    "details": '{"policy_relevance": "high"}',
                },
            ]
        ),
    )
    con.commit()
    claude = client.get("/api/documents", params={**params, "method": "llm:test", "mode": "scatter"}).json()
    assert {d["doc_id"]: d["score"] for d in claude["items"]} == {"speech_powell1": None, "speech_powell2": 0.5}
    assert claude["total"] == 2 and claude["low_relevance"] == 1
    listed = client.get("/api/documents", params={**params, "method": "llm:test", "offset": 0, "limit": 5}).json()
    assert {d["doc_id"]: d["score"] for d in listed["items"]}["speech_powell1"] == 0.0  # the table keeps each reading
    assert {d["doc_id"]: d["relevance"] for d in listed["items"]}["speech_powell1"] == "low"  # and marks it


def test_findings_judge_each_hypothesis_from_the_store(con):
    import json

    from fomc.api import app

    client = TestClient(app)
    assert client.get("/api/findings").json() == []  # no results yet: nothing is guessed
    llm = "llm:claude-opus-5-5:v1"
    db.upsert(
        con,
        "validity",
        pd.DataFrame(
            [{"method": llm, "n": 496, "macro_f1": 0.66}, {"method": "supervised", "n": 496, "macro_f1": 0.58}]
        ),
    )
    db.upsert(
        con,
        "event_study",
        pd.DataFrame(
            [
                {"doc_type": "presser", "method": llm, "regressor": "shift", "outcome": "d5y", "t": 4.12, "q_bh": 0.03},
                {"doc_type": "minutes", "method": llm, "regressor": "level", "outcome": "d2y", "t": 1.2, "q_bh": 0.6},
            ]
        ),
    )
    db.upsert(
        con,
        "backtests",
        pd.DataFrame([{"run_id": "primary", "is_primary": 1, "sharpe": -0.18, "psr": 0.2, "placebo_p": 0.28}]),
    )
    meta = {
        "validity_tests": [{"method": "supervised", "f1_diff": 0.08, "p_boot": 0.004}],
        "audit": {"identify": {"statement": {"exact_month": 0.99}}, "invariance": {"corr_stance_score": 0.99}},
    }
    con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    cards = {c["key"]: c for c in client.get("/api/findings").json()}
    assert {k: c["verdict"] for k, c in cards.items()} == {
        "h1": "Supported",
        "h2": "Supported",
        "h3": "Not supported",
        "h4": "Mixed",
    }
    assert (cards["h1"]["value"], cards["h1"]["unit"]) == ("0.66", "vs 0.58")
    assert (cards["h2"]["value"], cards["h2"]["unit"]) == ("1", "of 2 tests")
    assert "press conference tone shift on the 5-year, t = 4.12" in cards["h2"]["detail"]
    assert cards["h3"]["value"] == "−0.18" and "p = 0.28" in cards["h3"]["detail"]


def test_home_lists_only_documents_about_policy(con):
    from fomc.api import app

    llm = "llm:claude-opus-5-5:v1"
    rows = [  # Claude reads the speech as off-topic (bank supervision, say): it stays out of the Home list
        {"method": llm, "doc_id": "minutes_20240131", "score": 0.4, "details": '{"policy_relevance": "high"}'},
        {"method": llm, "doc_id": "speech_powell1", "score": 0.0, "details": '{"policy_relevance": "low"}'},
    ]
    db.upsert(con, "scores", pd.DataFrame(rows))
    con.commit()
    latest = TestClient(app).get("/api/overview").json()["latest"]
    assert [d["doc_id"] for d in latest] == ["minutes_20240131"] and latest[0]["score"] == 0.4


def test_public_mode_is_read_only(con, monkeypatch):
    from fomc import api

    monkeypatch.setattr(api, "PUBLIC", True)
    monkeypatch.setattr(api, "SCORE_TOKEN", "")
    client = TestClient(api.app)
    st = client.get("/api/settings").json()
    assert st["read_only"] is True and st["key_hint"] is None and st["score_enabled"] is False
    assert client.post("/api/settings", json={"api_key": "sk-ant-test-0000000000"}).status_code == 403
    assert client.post("/api/settings/check").status_code == 403
    assert client.post("/api/score", json={"text": "x" * 80, "doc_type": "speech"}).status_code == 403
    assert client.get("/api/health").json()["public"] is True
    assert client.get("/api/pulse").status_code == 200


def test_the_deck_has_its_own_address(con):
    from fomc.api import app

    client = TestClient(app)
    assert client.get("/story", follow_redirects=False).headers["location"] == "/#/story"
    assert client.get("/story?s=5", follow_redirects=False).headers["location"] == "/#/story?s=5"


def test_optional_login_guards_everything_but_health(con, monkeypatch):
    import base64

    from fomc import api

    monkeypatch.setattr(api, "BASIC_AUTH", "team:secret")
    client = TestClient(api.app)
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/health").status_code == 200
    token = base64.b64encode(b"team:secret").decode()
    assert client.get("/api/overview", headers={"Authorization": f"Basic {token}"}).status_code == 200


def _statements(con):
    from fomc import policy

    rows = [
        (
            "statement_20260617",
            "2026-06-17",
            "The Committee decided to maintain the target range for the federal "
            "funds rate at 3-1/2 to 3-3/4 percent.\n\nInflation remains elevated.",
        ),
        (
            "statement_20260916",
            "2026-09-16",
            "The Committee decided to raise the target range for the federal "
            "funds rate to 3-3/4 to 4 percent.\n\nInflation remains elevated and broad.",
        ),
    ]
    docs = pd.DataFrame(
        [
            {
                "doc_id": d,
                "doc_type": "statement",
                "meeting_date": t,
                "release_date": t,
                "release_time_et": "14:00",
                "note": None,
                "text": x,
            }
            for d, t, x in rows
        ]
    )
    db.upsert(con, "documents", docs)
    db.upsert(con, "decisions", policy.decisions(docs))


def test_tracker_and_redline_endpoints(con):
    from fomc.api import app

    _statements(con)
    client = TestClient(app)
    t = client.get("/api/tracker").json()
    assert t["current"]["doc_id"] == "statement_20260916" and t["current"]["change_bp"] == 25
    assert t["current"]["range_high"] == 4.0 and len(t["decisions"]) == 2
    red = client.get("/api/documents/statement_20260916/diff").json()
    assert red["prev_doc_id"] == "statement_20260617" and red["words_added"] >= 2
    assert {s["op"] for s in red["segments"]} == {"equal", "insert", "delete"}
    assert client.get("/api/documents/statement_20260617/diff").status_code == 404  # first decision
    assert client.get("/api/documents/statement_20260916").json()["decision"]["action"] == 1


def _label_set(con, n=24):
    from fomc import labels

    sentences = " ".join(
        f"Participants noted that inflation in sector number {i} remained above the goal." for i in range(n)
    )
    db.upsert(
        con,
        "documents",
        pd.DataFrame(
            [
                {
                    "doc_id": "statement_20260729",
                    "doc_type": "statement",
                    "release_date": "2026-07-29",
                    "release_time_et": "14:00",
                    "note": None,
                    "text": sentences,
                }
            ]
        ),
    )
    return labels.sample(con, n=n, after="2026-07-01")


def test_team_labels_flow_and_agreement(con):
    from fomc import labels
    from fomc.api import app

    assert _label_set(con) == 24
    labels.predict(con)
    client = TestClient(app)
    first = client.get("/api/labels/next", params={"annotator": "hl"}).json()
    assert first["progress"] == {"done": 0, "total": 24}
    r = client.post("/api/labels", json={"item_id": first["item"]["item_id"], "annotator": "hl", "label": 1}).json()
    assert r["progress"]["done"] == 1 and r["item"]["item_id"] != first["item"]["item_id"]
    back = client.post("/api/labels/undo", json={"annotator": "hl"}).json()
    assert back["item"]["item_id"] == first["item"]["item_id"] and back["progress"]["done"] == 0
    assert client.post("/api/labels", json={"item_id": 999999, "annotator": "hl", "label": 0}).status_code == 404
    assert client.post("/api/labels", json={"item_id": 1, "annotator": "hl", "label": 2}).status_code == 422
    ids = [r[0] for r in con.execute("SELECT item_id FROM label_items ORDER BY item_id")]
    for k, i in enumerate(ids[:12]):
        for who in ("hl", "lr"):
            labels.record(con, i, who, (k % 3) - 1)
    s = client.get("/api/labels/summary").json()
    assert s["items"] == 24 and s["writable"] is True
    assert s["pairs"][0]["kappa"] == 1.0 and s["pairs"][0]["n"] == 12
    assert any(m["method"] == "dictionary" and m["n"] == 12 for m in s["methods"])


def test_public_mode_blocks_labeling(con, monkeypatch):
    from fomc import api

    _label_set(con, n=4)
    monkeypatch.setattr(api, "PUBLIC", True)
    client = TestClient(api.app)
    assert client.get("/api/labels/summary").json()["writable"] is False
    assert client.get("/api/labels/next", params={"annotator": "x"}).json()["item"] is not None
    assert client.post("/api/labels", json={"item_id": 1, "annotator": "x", "label": 0}).status_code == 403
    assert client.post("/api/labels/undo", json={"annotator": "x"}).status_code == 403


def test_migration_from_v2_rebuilds_derived_tables(tmp_path, monkeypatch):
    path = tmp_path / "v2.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '2'), ('fp:evaluate', 'abc'), ('fp:collect', 'keep');
        CREATE TABLE event_study (doc_type TEXT, method TEXT, regressor TEXT, outcome TEXT, n INTEGER,
            beta_bp_per_sd REAL, t REAL, p REAL, r2 REAL, updated_at TEXT,
            PRIMARY KEY (doc_type, method, regressor, outcome));
        INSERT INTO event_study VALUES ('minutes', 'm', 'level', 'd2y', 100, 1.0, 2.0, 0.05, 0.1, 'x');
    """)
    old.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    c = db.connect()
    db.init(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(event_study)")}
    assert {"sample", "control", "q_bh"} <= cols
    assert c.execute("SELECT count(*) FROM event_study").fetchone()[0] == 0  # rebuilt by the next run
    keys = {r[0] for r in c.execute("SELECT key FROM meta")}
    assert "fp:evaluate" not in keys and "fp:collect" in keys
    assert {"decisions", "label_items", "labels", "event_curves"} <= {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def test_fed_dashboard_endpoint(con):
    from fomc.api import app

    _statements(con)
    db.upsert(con, "policy_rates", pd.DataFrame([{"date": "2026-10-15", "effr": 3.88, "sofr": 3.89}]))
    db.upsert(con, "yields", pd.DataFrame([{"date": "2026-10-16", "t3m": 4.2, "t2y": 4.74, "t10y": 5.09, "t5y": 4.9}]))
    db.upsert(
        con,
        "committee",
        pd.DataFrame(
            [
                {
                    "name": "Jerome H. Powell",
                    "status": "voter",
                    "board": 1,
                    "role": "Governor",
                    "bank": None,
                    "fomc_vice_chair": 0,
                    "as_of": "2026-10-07",
                },
                {
                    "name": "John C. Williams",
                    "status": "voter",
                    "board": 0,
                    "role": "President, New York",
                    "bank": "New York",
                    "fomc_vice_chair": 1,
                    "as_of": "2026-10-07",
                },
            ]
        ),
    )
    r = TestClient(app).get("/api/fed").json()
    assert r["current"]["range_high"] == 4.0 and r["current"]["vote"] == "2–0"
    assert r["effr"]["effr"] == 3.88 and r["market"]["t2y_minus_effr_bp"] == 86
    assert [m["name"] for m in r["members"]] == ["John C. Williams", "Jerome H. Powell"]  # FOMC Vice Chair first
    powell = r["members"][1]
    assert powell["last_speech"]["doc_id"] == "speech_powell1" and powell["tone_pct"] is None  # needs 3 speeches


def test_read_only_endpoints_revalidate_with_etags(con):
    from fomc.api import app

    client = TestClient(app)
    first = client.get("/api/overview")
    tag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"
    again = client.get("/api/overview", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert "etag" not in client.get("/api/settings").headers  # depends on .env, never cached
    con.execute("INSERT INTO meta VALUES ('touch', '1')")
    con.commit()
    assert client.get("/api/overview", headers={"If-None-Match": tag}).status_code == 200  # the store changed


def test_backtest_curve_on_an_aggregate_bond_portfolio(con):
    from fomc.api import app

    dates = pd.bdate_range("2024-01-01", periods=4)
    db.upsert(
        con,
        "etf_prices",
        pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "SHY": 1.0,
                "IEI": 1.0,
                "IEF": 1.0,
                "TLT": 1.0,
                "AGG": [100, 101, 101, 102],
            }
        ),
    )
    store.save_backtests(
        con, pd.DataFrame([{"run_id": "r1", "method": "m"}]), {"r1": pd.Series([0.0, 0.01, -0.01, 0.0], index=dates)}
    )
    client = TestClient(app)
    plain = client.get("/api/backtests/curve", params={"run_id": "r1"}).json()
    assert set(plain[0]) == {"date", "cum"}
    rows = client.get("/api/backtests/curve", params={"run_id": "r1", "benchmark": "AGG"}).json()
    assert np.isclose(rows[-1]["bench"], 0.02, atol=1e-6) and rows[-1]["port"] != rows[-1]["bench"]
    assert client.get("/api/backtests/curve", params={"run_id": "r1", "benchmark": "SPY"}).status_code == 400


def test_story_deck_builds_from_a_sparse_store(con, tmp_path):
    """The Story page and `fomc slides` share one builder; slides whose data is missing drop out, the rest renumber."""
    from fomc import api, slides, story
    from fomc.config import settings

    deck = TestClient(api.app).get("/api/story").json()
    ids = [s["id"] for s in deck["slides"]]
    assert ids[:5] == ["cover", "agenda", "primer", "brief", "course-links"] and ids[-1] == "closing"
    assert "contributions" not in ids
    assert len(set(ids)) == len(ids) and [s["n"] for s in deck["slides"]] == list(range(1, len(ids) + 1))
    assert deck["team"] == settings()["project"]["team"] == sorted(deck["team"])  # alphabetical by first name
    assert {"architecture", "screens", "tech-rubric", "tech-store", "tech-serving", "tech-deploy"} <= set(ids)
    assert not {"tech-cover", "tech-agenda", "tech-closing", "part01", "tech-part01"} & set(ids)
    spans = [tuple(map(int, r[2].split("-"))) for r in deck["slides"][1]["visual"]["rows"]]
    assert spans[0][0] == 3 and spans[-1][1] == len(ids)
    assert all(left[1] + 1 == right[0] for left, right in zip(spans, spans[1:]))
    assert deck["slides"][0]["title"] == "FOMC Tone Lab"
    assert story.decision_mix({1: 21, -1: 11, 0: 111}) == "21 hikes, 11 cuts, 111 holds"  # action codes, not names
    out = slides.outline(story.build(con), tmp_path / "outline.md").read_text()
    assert "Genie Zhang" in out and "**The Fed speaks**" in out and "defined rubric with evidence spans →" in out
    tech = TestClient(api.app).get("/api/story", params={"deck": "technical"}).json()
    ids = [s["id"] for s in tech["slides"]]
    assert tech["deck"] == "technical" and ids[0] == "tech-cover" and ids[-1] == "tech-closing"
    assert len(set(ids)) == len(ids) and [s["n"] for s in tech["slides"]] == list(range(1, len(ids) + 1))
    assert {"tech-rubric", "tech-store", "tech-serving", "tech-deploy", "tech-codemap"} <= set(ids)  # no data needed
    assert TestClient(api.app).get("/api/story", params={"deck": "other"}).status_code == 404
    first = TestClient(api.app).get("/story", params={"deck": "technical", "s": 3}, follow_redirects=False)
    assert first.headers["location"] == "/#/story?deck=technical&s=3"
    for built in (deck, tech):
        long = [s["title"] for s in built["slides"] if s["layout"] in ("standard", "wide") and len(s["title"]) > 52]
        assert not long, long  # one line on the slide; the rest goes in the subtitle
    text = slides.outline(story.build(con, "technical"), tmp_path / "outline-technical.md").read_text()
    assert text.startswith("# FOMC Tone Lab: the technical appendix") and "```text" in text


def test_shared_team_names_stay_native_on_cover_and_close_without_role_placeholders(con, tmp_path, monkeypatch):
    """Credit every configured member on both ends, without a separate allocation of overlapping work."""
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from fomc import slides, story
    from fomc.config import settings

    configured = settings()["project"]["team"]
    team = ["Team member A", "Team member B", "Team member C", "Team member D"]
    monkeypatch.setitem(settings()["project"], "team", team)
    deck = story.build(con)
    assert team != configured  # the builder reads settings rather than copying the current names
    assert "contributions" not in [s["id"] for s in deck["slides"]]
    cover, closing = deck["slides"][0], deck["slides"][-1]
    assert cover["id"] == "cover" and closing["id"] == "closing"
    assert cover["team"] == closing["team"] == team
    outline = slides.outline(deck, tmp_path / "outline.md").read_text()
    assert "Team contributions" not in outline and "【填写】" not in outline

    # A two-slide export needs no visual captures, so any raster fallback fails this check.
    path = slides.editable_deck({**deck, "slides": [cover, closing]}, {}, tmp_path / "editable.pptx")
    ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    }
    with ZipFile(path) as package:
        for i in (1, 2):
            xml = ET.fromstring(package.read(f"ppt/slides/slide{i}.xml"))
            words = [node.text for node in xml.findall(".//a:t", ns)]
            assert all(name in words for name in team)
            assert "Team contributions" not in words and "【填写】" not in words
            assert not xml.findall(".//p:pic", ns)


def test_the_trained_reader_follows_validity_and_keeps_the_takeaway_honest(con):
    """The fine-tuned RoBERTa gets its own slide after Validity, worded from its result, and a lead over Claude
    qualifies the takeaway; it never enters H1."""
    import json

    from fomc import findings, story

    rows = [
        ("llm:claude-opus-5-5", 496, 0.677, 0.661, 0.485),
        ("supervised", 496, 0.601, 0.578, 0.361),
        ("roberta_tuned", 496, 0.712, 0.703, 0.552),
    ]
    con.executemany("INSERT INTO validity VALUES (?, ?, ?, ?, ?, '2026-10-22')", rows)
    claude = pd.DataFrame({"doc_id": ["minutes_20240131"], "score": [-0.4], "n": [1]})
    store.save_scores(con, "llm:claude-opus-5-5", claude)
    cfg = {"backbone": "FacebookAI/roberta-large", "lr": 1e-5, "llrd": 1.0, "batch": 16}
    reader = {
        "types": {"minutes": {"n": 142, "pearson": 0.86, "spearman": 0.84}},
        "chosen": {"config": cfg, "epoch": 6, "cv_macro_f1": 0.72},
        "search": [{"config": cfg, "best_epoch": 6, "cv_macro_f1": 0.72, "fold_sd": 0.02}] * 9,
        "seed_macro_f1": [0.69, 0.71],
        "scores": {"minutes_20240131": -0.21},
    }
    con.execute("INSERT INTO meta VALUES ('readers', ?)", (json.dumps({"roberta_tuned": reader}),))
    con.commit()
    deck = story.build(con)["slides"]
    ids = [s["id"] for s in deck]
    assert ids.index("local-training") < ids.index("tech-search") < ids.index("validity") < ids.index("readers")
    slide = deck[ids.index("readers")]
    assert slide["number"] == "0.70" and slide["title"] == "Trained on the labels, RoBERTa beats Claude"
    assert "1,984 hand-labeled sentences" in slide["subtitle"]
    assert "learning rate 1e-5, 6 epochs" in slide["chips"][0] and "minutes 0.86" in slide["chips"][2]
    assert slide["visual"]["points"] == [["minutes", -0.4, -0.21]]
    take = deck[ids.index("takeaways")]["visual"]["cards"][0]
    assert "public expert labels" in take[0] and "0.70" in take[1]
    h1 = next(f for f in findings.summary(con) if f["key"] == "h1")
    assert h1["unit"] == "vs 0.58"  # H1 still compares Claude with the baselines it was stated against


def test_the_feed_gives_each_new_document_its_reading_and_the_feds_words(con):
    """/feed.xml: newest first, the lean in the Home page's words, the percentile against earlier documents only,
    Claude's quoted evidence, and links on the public address behind the proxy."""
    import json
    from xml.etree import ElementTree as ET

    from fomc import api

    method = "llm:claude-opus-5-5:v1"
    statement = {"doc_id": "statement_20240320", "doc_type": "statement", "release_date": "2024-03-20", "note": None}
    db.upsert(con, "documents", pd.DataFrame([{**statement, "release_time_et": "14:00", "n_words": 5}]))
    ids = ["minutes_20240131", "speech_powell1", "statement_20240320"]
    scores = pd.DataFrame({"doc_id": ids, "score": [0.4, -0.2, 0.1], "policy_relevance": ["high"] * 3})
    store.save_scores(con, method, scores)
    parsed = {"evidence": [{"dimension": "inflation_assessment", "quote": "expectations remained well anchored"}]}
    con.execute(
        "INSERT INTO llm_records (path, key, mode, model, rubric_version, run_tag, status, parsed) "
        "VALUES ('p', 'minutes_20240131', 'level', 'claude-opus-5-5', 'v1', '', 'ok', ?)",
        (json.dumps(parsed),),
    )
    shift = {"shift_score": 1, "rationale": "Drops the easing bias."}
    con.execute(
        "INSERT INTO llm_records (path, key, mode, model, rubric_version, run_tag, status, parsed) "
        "VALUES ('q', 'statement_20240320', 'shift', 'claude-opus-5-5', 'v1', '', 'ok', ?)",
        (json.dumps(shift),),
    )
    con.commit()
    proxy = {"x-forwarded-host": "fedtone.web.app", "x-forwarded-proto": "https"}
    r = TestClient(api.app).get("/feed.xml", headers=proxy)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/atom+xml") and r.headers["etag"]
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = ET.fromstring(r.content).findall("a:entry", ns)
    titles = [e.find("a:title", ns).text for e in entries]
    assert titles == [
        "Statement, 20 March 2024: balanced (+0.10); against the last decision, more hawkish",
        "Speech by Jerome H. Powell, 1 March 2024: dovish (-0.20)",
        "Minutes, 21 February 2024: hawkish (+0.40)",
    ]
    assert "<p>Drops the easing bias.</p>" in entries[0].find("a:content", ns).text
    body = entries[2].find("a:content", ns).text
    assert "<blockquote>expectations remained well anchored</blockquote>" in body
    assert 'href="https://fedtone.web.app/#/documents?doc=minutes_20240131"' in body


def test_team_labels_travel_through_git_files(con, monkeypatch):
    from fomc import labels

    _label_set(con)
    ids = [r[0] for r in con.execute("SELECT item_id FROM label_items ORDER BY item_id LIMIT 3")]
    for i, lab in zip(ids, (1, 0, -1)):
        labels.record(con, i, "GZ", lab)
    path = labels.label_file("GZ")
    assert path.name == "gz.csv" and len(pd.read_csv(path)) == 3
    labels.undo(con, "GZ")
    assert len(pd.read_csv(path)) == 2  # the file follows the undo
    # another machine: same sentences under different item ids, and a stale label the file no longer has
    con.execute("DELETE FROM labels")
    con.execute("UPDATE label_items SET item_id = item_id + 1000")
    con.execute("INSERT INTO labels VALUES (?, 'GZ', 1, '2026-01-01')", (ids[2] + 1000,))
    con.commit()
    r = labels.import_files(con)
    assert r == {"files": 1, "labels": 2, "unmatched": 0}
    got = dict(con.execute("SELECT item_id, label FROM labels WHERE annotator = 'GZ'").fetchall())
    assert got == {ids[0] + 1000: 1, ids[1] + 1000: 0}


def test_reliability_endpoint_reads_tests_and_audit(con):
    import json

    from fomc.api import app

    client = TestClient(app)
    assert client.get("/api/reliability").json() == {
        "tests": [],
        "readers": {},
        "stability": None,
        "identify": None,
        "invariance": None,
        "drift": None,
    }
    tests = [
        {"target": "llm:m", "method": "supervised", "f1_diff": 0.08, "ci_low": 0.03, "ci_high": 0.14, "p_boot": 0.004}
    ]
    audit = {
        "stability": {"n": 152, "overall_stance_agreement": 0.9},
        "invariance": {"n": 60, "corr_stance_score": 0.99},
    }
    con.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)",
        [
            ("validity_tests", json.dumps(tests)),
            ("audit", json.dumps(audit)),
            ("readers", json.dumps({"roberta_tuned": {"types": {"minutes": {"n": 142, "pearson": 0.8}}}})),
        ],
    )
    con.commit()
    r = client.get("/api/reliability").json()
    assert r["tests"][0]["method"] == "supervised" and r["stability"]["n"] == 152 and r["invariance"]["n"] == 60
    assert r["readers"]["roberta_tuned"]["types"]["minutes"]["n"] == 142


def test_llm_sync_counts_a_moved_record_once(con, tmp_path, monkeypatch):
    """Superseded records move to their own folder for provenance; the store must not keep the old path too."""
    import json

    from fomc.llm import rubric, scorer

    monkeypatch.setattr(store, "LLM_DIR", tmp_path)
    monkeypatch.setattr(scorer, "LLM_DIR", tmp_path)
    rec = {
        "key": "minutes_20240131",
        "mode": "shift",
        "model_requested": "m",
        "rubric_version": rubric.RUBRIC_VERSION,
        "status": "ok",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "parsed": {"shift_score": 1},
        "checks": {"before": {"share": 1.0}, "after": {"share": 1.0}},
    }
    live = tmp_path / "m" / rubric.RUBRIC_VERSION / "shift"
    live.mkdir(parents=True)
    (live / "minutes_20240131.json").write_text(json.dumps(rec))
    store.sync_llm(con)
    old = live.parent / "shift_superseded"
    old.mkdir()
    (live / "minutes_20240131.json").rename(old / "minutes_20240131.json")
    store.sync_llm(con)
    paths = [r[0] for r in con.execute("SELECT path FROM llm_records")]
    assert paths == [f"m/{rubric.RUBRIC_VERSION}/shift_superseded/minutes_20240131.json"]
