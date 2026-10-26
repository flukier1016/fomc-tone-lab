"""A member over time: the Fed's own sentences about them, their titles, their dissents and where their tone shifted."""

import json

import numpy as np
import pandas as pd
import pytest

from fomc import fed, members

BOARD_PAGE = """<html><body><p>Skip to main content</p>
<p>Philip N. Jefferson took office as the Vice Chair of the Board of Governors of the Federal Reserve System on
September 13, 2023, for a four-year term. Dr. Jefferson has served as a member of the Board of Governors of the Federal
Reserve System since taking office on May 23, 2022, to fill an unexpired term ending January 31, 2036.</p>
<p>Before then, Dr. Jefferson served as the Robert P. Gwinn Professor of Economics at a college.</p>
<p>Dr. Jefferson received a BA in economics from Vassar College and a PhD in economics from the University of
Virginia.</p></body></html>"""

BANK_PAGE = """<html><body><p>Lorie K. Logan took office on August 22, 2022, as the 14th president and chief executive
officer of the 11th District, Federal Reserve Bank of Dallas. <a href="https://www.dallasfed.org/fed/leadership/logan.aspx">
Read more</a></p></body></html>"""


def test_the_biography_is_quoted_and_dated_from_the_feds_own_page():
    said = fed.bio_sentences(BOARD_PAGE, "Philip N. Jefferson")
    assert said["took"].startswith("Dr. Jefferson has served as a member of the Board")  # joining, not the later title
    assert said["role"].startswith("Philip N. Jefferson took office as the Vice Chair")
    assert said["before"].endswith(
        "the Robert P. Gwinn Professor of Economics at a college."
    )  # an initial is no full stop
    assert said["school"].startswith("Dr. Jefferson received a BA")
    assert members.offices(said) == [
        {"date": "2022-05-23", "office": "Board member"},
        {"date": "2023-09-13", "office": "Vice Chair"},
    ]
    assert fed.read_more(BANK_PAGE, "Lorie K. Logan") == "https://www.dallasfed.org/fed/leadership/logan.aspx"
    assert set(fed.bio_sentences(BANK_PAGE, "Lorie K. Logan")) == {"took"}  # the rest is on the Reserve Bank's page
    assert members.office("Cheryl Venable is the interim president and chief executive officer") == "Interim president"
    assert members.office("Kevin Warsh took office as chairman of the Board of Governors") == "Chair"
    assert fed._DEGREE.search("Ms. Shukla has extensive experience") is None  # "Ms." is not a master's degree


def test_a_shift_in_tone_is_found_where_it_happened_and_not_in_noise():
    rng = np.random.default_rng(7)
    dates = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in (5, 20)] + [f"2025-{m:02d}-05" for m in range(1, 9)]
    hawkish, dovish = rng.normal(0.4, 0.2, 20), rng.normal(-0.4, 0.2, 12)
    found = members.regimes(dates, list(np.concatenate([hawkish, dovish])))
    assert [(r["from"], r["n"]) for r in found] == [("2024-01-05", 20), ("2024-11-05", 12)]
    assert found[0]["mean"] > 0.2 and found[1]["mean"] < -0.2
    flat = members.regimes(dates, list(rng.normal(0, 0.4, len(dates))))
    assert len(flat) == 1 and flat[0]["n"] == len(dates)  # nothing changed: one stretch
    assert members.regimes(dates[:4], [0.1, 0.2, 0.3, 0.4]) == [
        {"from": dates[0], "to": dates[3], "n": 4, "mean": pytest.approx(0.25)}
    ]  # too few speeches to split


def test_what_changed_reads_titles_dissents_and_shifts():
    speeches = pd.DataFrame(
        {
            "doc_id": [f"s{i}" for i in range(4)],
            "date": ["2023-05-01", "2023-10-09", "2024-02-01", "2024-06-01"],
            "title": ["A", "B", "C", "D"],
            "role": ["Governor", "Vice Chair", "Vice Chair", "Vice Chair"],
            "score": [0.2, 0.9, -0.8, 0.0],
            "relevance": ["high", "high", "high", "low"],
        }
    )
    spells = members.role_spells(speeches)
    assert [(s["role"], s["n"]) for s in spells] == [("Governor", 1), ("Vice Chair", 3)]
    votes = pd.DataFrame(
        [{"doc_id": "statement_20241218", "date": "2024-12-18", "name": "Philip N. Jefferson", "preferred": "hold",
          "reason": "preferred to maintain the target range"}]
    )  # fmt: skip
    stretches = [
        {"from": "2023-05-01", "to": "2023-10-09", "n": 5, "mean": 0.5},
        {"from": "2024-02-01", "to": "2024-06-01", "n": 6, "mean": -0.4},
    ]
    dated = [{"date": "2022-05-23", "office": "Board member"}, {"date": "2023-09-13", "office": "Vice Chair"}]
    out = members.events(speeches, spells, stretches, votes, dated, {"statement_20241218": -1})
    kinds = [(e["date"], e["kind"]) for e in out]
    assert kinds == [
        ("2024-12-18", "dissent"), ("2024-02-01", "shift"), ("2023-09-13", "office"), ("2022-05-23", "office"),
    ]  # fmt: skip
    dissent = out[0]
    assert dissent["direction"] == 1  # no change against a cut: the hawkish side
    assert dissent["detail"] == "In the statement's words, Jefferson preferred to maintain the target range."
    assert out[1]["direction"] == -1 and "more dovish" in out[1]["text"]
    easing = "supported maintaining the target range but did not support inclusion of an easing bias in the statement"
    assert members.lean("other", 0, easing) == 1 and members.dissent_label("other", easing) == "against an easing bias"
    assert (
        members.lean("hold", 1) == -1
        and members.dissent_label("other", "preferred to continue the decline in securities holdings")
        == "on the balance sheet"
    )
    # the speech titles' change to Vice Chair is dated by the biography already, so it is not listed twice;
    # four speeches are too few to name the most hawkish and the most dovish


def test_the_member_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fomc import db, policy
    from fomc.api import app

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    con = db.connect()
    db.init(con)
    statements = pd.DataFrame(
        [
            {"doc_id": "statement_20250917", "doc_type": "statement", "meeting_date": "2025-09-17",
             "release_date": "2025-09-17", "note": None,
             "text": "The Committee decided to lower the target range for the federal funds rate to 4 to 4-1/4 "
             "percent. Voting against this action was Beth M. Hammack, who preferred no change to the target range."},
        ]
    )  # fmt: skip
    speeches = pd.DataFrame(
        [
            {"doc_id": f"speech_w{i}", "doc_type": "speech", "release_date": f"2025-{i + 1:02d}-10", "note": None,
             "speaker": "Christopher J. Waller", "speaker_role": "Governor", "title": f"Talk {i}", "text": "x"}
            for i in range(6)
        ]
    )  # fmt: skip
    db.upsert(con, "documents", pd.concat([statements, speeches]))
    db.upsert(con, "decisions", policy.decisions(statements))
    db.upsert(
        con,
        "scores",
        pd.DataFrame(
            {"method": "supervised", "doc_id": speeches["doc_id"], "score": [0.5, 0.4, 0.6, -0.2, 0.1, 0.3],
             "details": [json.dumps({"policy_relevance": "high"})] * 5 + [json.dumps({"policy_relevance": "low"})]}
        ),
    )  # fmt: skip
    rows = [
        {"name": "Christopher J. Waller", "status": "voter", "board": 1, "role": "Governor", "bank": None},
        {"name": "Beth M. Hammack", "status": "voter", "board": 0, "role": "President, Cleveland", "bank": "Cleveland"},
    ]
    db.upsert(con, "committee", pd.DataFrame([{**r, "fomc_vice_chair": 0, "as_of": "2026-10-07"} for r in rows]))
    bios = {
        "Beth M. Hammack": {
            "took": "Beth M. Hammack took office on August 21, 2024, as the 12th president of the Bank.",
            "sources": ["https://www.federalreserve.gov/aboutthefed/federal-reserve-system-cleveland.htm"],
        }
    }
    con.execute("INSERT INTO meta VALUES ('bios', ?)", (json.dumps(bios),))
    con.commit()
    client = TestClient(app)
    w = client.get("/api/member", params={"name": "Christopher J. Waller"}).json()
    assert [s["doc_id"] for s in w["speeches"]] == [f"speech_w{i}" for i in range(6)]
    assert w["regimes"] == [
        {"from": "2025-01-10", "to": "2025-05-10", "n": 5, "mean": pytest.approx(0.28)}
    ]  # low relevance left out
    assert w["bio"] is None and w["took_office"] is None and w["dissents"] == []
    h = client.get("/api/member", params={"name": "Beth M. Hammack"}).json()
    assert h["speeches"] == [] and h["took_office"] == "2024-08-21" and h["office"] == "President"
    assert [(e["kind"], e.get("direction")) for e in h["events"]] == [("dissent", 1), ("office", None)]
    assert client.get("/api/member", params={"name": "Nobody"}).status_code == 404
    card = next(m for m in client.get("/api/fed").json()["members"] if m["name"] == "Beth M. Hammack")
    assert card["took_office"] == "2024-08-21" and card["background"] == bios["Beth M. Hammack"]["took"]  # no "before"
    con.close()
