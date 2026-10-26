"""Build the document index.

One row per statement, minutes, press conference transcript and Board speech
in the sample, with the moment it became public. Clean texts go to
data/interim/texts/<doc_id>.txt; the index goes to data/interim/documents.csv.

Dates come from the document URLs (monetaryYYYYMMDDa.htm, fomcminutesYYYYMMDD.htm,
...), which is more robust than parsing the free-text dates on the pages.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from . import http, textclean
from .config import INTERIM, ensure_dirs, settings

FED = "https://www.federalreserve.gov"
CALENDAR = FED + "/monetarypolicy/fomccalendars.htm"
HISTORICAL = FED + "/monetarypolicy/fomchistorical{year}.htm"
SPEECHES_JSON = FED + "/json/ne-speeches.json"
PRESSER_PDF = FED + "/mediacenter/files/FOMCpresconf{date}.pdf"

STATEMENT_HREF = re.compile(r"monetary/?(\d{8})a\.htm|/press/monetary/\d{4}/(\d{8})/")
MINUTES_HREF = re.compile(r"fomcminutes(\d{8})\.htm|/fomc/minutes/(\d{8})\.htm")
PRESSER_HREF = re.compile(r"fomcpres+conf(\d{8})\.htm")
RELEASED = re.compile(r"Released ([A-Z][a-z]{2,}\.? \d{1,2}, \d{4})")
ROLE = re.compile(r"^(Vice Chair(?:man)? for Supervision|Vice Chair(?:man)?|Chair(?:man)?|Governor)\s+(.*)$")

COLUMNS = [
    "doc_id",
    "doc_type",
    "meeting_date",
    "release_date",
    "release_time_et",
    "time_source",
    "info_start_et",
    "url",
    "speaker",
    "speaker_role",
    "title",
    "n_words",
    "text_sha256",
    "note",
]


def _date(s: str) -> str:
    return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")


def _parse_released(text: str) -> str | None:
    m = RELEASED.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _links(block, rx: re.Pattern) -> tuple[str | None, str | None]:
    for a in block.select("a[href]"):
        m = rx.search(a["href"])
        if m:
            href = a["href"] if a["href"].startswith("http") else FED + a["href"]
            return href, _date(next(g for g in m.groups() if g))
    return None, None


def _meeting(block) -> dict | None:
    statement_url, decision = _links(block, STATEMENT_HREF)
    minutes_url, minutes_date = _links(block, MINUTES_HREF)
    presser_url, presser_date = _links(block, PRESSER_HREF)
    if not (statement_url or minutes_url):
        return None
    return {
        "decision_date": decision or minutes_date,
        "statement_url": statement_url,
        "minutes_url": minutes_url,
        "minutes_released": _parse_released(block.get_text(" ", strip=True)),
        "presser_date": presser_date,
    }


def meetings() -> pd.DataFrame:
    """Every FOMC meeting or call with a statement or minutes link, oldest first."""
    soup = BeautifulSoup(http.get(CALENDAR, refresh=True), "lxml")
    rows, calendar_years = [], set()
    for panel in soup.select("div.panel.panel-default"):
        heading = panel.select_one(".panel-heading")
        year = re.search(r"(\d{4})", heading.get_text() if heading else "")
        if year:
            calendar_years.add(int(year.group(1)))
        for row in panel.select("div.fomc-meeting"):
            m = _meeting(row)
            if m:
                rows.append(m)
    first_calendar_year = min(calendar_years)
    start = min(settings()["sample"]["fomc_start_year"], settings()["sample"]["presser_start_year"])
    for year in range(start, first_calendar_year):
        hist = BeautifulSoup(http.get(HISTORICAL.format(year=year)), "lxml")
        for panel in hist.select("div.panel.panel-default"):
            m = _meeting(panel)
            if m:
                rows.append(m)
    df = pd.DataFrame(rows).dropna(subset=["decision_date"])
    return df.drop_duplicates("decision_date").sort_values("decision_date").reset_index(drop=True)


MONTHS = {
    m: i
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}


def upcoming_meetings() -> list[str]:
    """Decision dates (second day) of scheduled meetings on the calendar page, today or later."""
    soup = BeautifulSoup(http.get(CALENDAR), "lxml")
    out = []
    for panel in soup.select("div.panel.panel-default"):
        year = re.search(r"(\d{4})", (panel.select_one(".panel-heading") or soup).get_text())
        if not year:
            continue
        for row in panel.select("div.fomc-meeting"):
            month_el, date_el = row.select_one(".fomc-meeting__month"), row.select_one(".fomc-meeting__date")
            if not month_el or not date_el:
                continue
            months = [w[:3] for w in re.findall(r"[A-Za-z]+", month_el.get_text())]  # "Apr/May" -> Apr, May
            days = re.findall(r"\d{1,2}", date_el.get_text())  # "27-28*" -> 27, 28
            if not months or not days:
                continue
            month = MONTHS.get(months[-1].lower())
            if month is None:
                continue
            try:
                out.append(datetime(int(year.group(1)), month, int(days[-1])).strftime("%Y-%m-%d"))
            except ValueError:
                continue
    today = datetime.now().strftime("%Y-%m-%d")
    return sorted({d for d in out if d >= today})


def _fomc_documents(mt: pd.DataFrame) -> list[dict]:
    cfg = settings()
    defaults = cfg["release_time_defaults_et"]
    docs = []
    for m in mt.itertuples():
        year = int(m.decision_date[:4])
        if pd.notna(m.statement_url) and year >= cfg["sample"]["fomc_start_year"]:
            docs.append(
                {
                    "doc_id": f"statement_{m.decision_date.replace('-', '')}",
                    "doc_type": "statement",
                    "meeting_date": m.decision_date,
                    "release_date": m.decision_date,
                    "url": m.statement_url,
                    "default_time": defaults["statement"] if year >= 2013 else defaults["statement_pre2013"],
                }
            )
        if pd.notna(m.minutes_url) and year >= cfg["sample"]["fomc_start_year"]:
            docs.append(
                {
                    "doc_id": f"minutes_{m.decision_date.replace('-', '')}",
                    "doc_type": "minutes",
                    "meeting_date": m.decision_date,
                    "release_date": m.minutes_released,
                    "url": m.minutes_url,
                    "default_time": defaults["minutes"],
                }
            )
        if pd.notna(m.presser_date) and year >= cfg["sample"]["presser_start_year"]:
            docs.append(
                {
                    "doc_id": f"presser_{m.presser_date.replace('-', '')}",
                    "doc_type": "presser",
                    "meeting_date": m.decision_date,
                    "release_date": m.presser_date,
                    "url": PRESSER_PDF.format(date=m.presser_date.replace("-", "")),
                    "default_time": defaults["presser_end"],
                    "info_start_et": defaults["presser_start"],
                }
            )
    return docs


def _speech_documents() -> list[dict]:
    cfg = settings()["sample"]
    entries = json.loads(http.get(SPEECHES_JSON, refresh=True).decode("utf-8-sig"))
    docs, seen = [], set()
    for e in entries:
        if "d" not in e or not e.get("l") or e["l"] in seen:  # empty link = repeat delivery, no page
            continue
        seen.add(e["l"])
        role = ROLE.match(e.get("s", "").strip())
        if not role:
            continue
        role_name = role.group(1).replace("Chairman", "Chair")
        if role_name not in cfg["speakers"]:
            continue
        has_time = ":" in e["d"]
        ts = datetime.strptime(e["d"], "%m/%d/%Y %I:%M:%S %p" if has_time else "%m/%d/%Y")
        if ts.year < cfg["speech_start_year"]:
            continue
        slug = e["l"].rstrip("/").split("/")[-1].rsplit(".", 1)[0]
        docs.append(
            {
                "doc_id": f"speech_{slug}",
                "doc_type": "speech",
                "meeting_date": None,
                "release_date": ts.strftime("%Y-%m-%d"),
                "release_time_et": ts.strftime("%H:%M") if has_time else None,
                "time_source": "speech_json" if has_time else None,
                "url": e["l"] if e["l"].startswith("http") else FED + e["l"],
                "speaker": html.unescape(role.group(2)),
                "speaker_role": role_name,
                "title": html.unescape(e.get("t") or ""),
            }
        )
    return docs


def _clean(doc: dict, raw: bytes) -> tuple[str, dict]:
    if doc["doc_type"] == "statement":
        return textclean.statement_text(raw)
    if doc["doc_type"] == "minutes":
        return textclean.minutes_text(raw)
    if doc["doc_type"] == "presser":
        return textclean.presser_text(raw)
    if doc["url"].lower().endswith(".pdf"):
        return textclean.pdf_text(raw), {}
    return textclean.speech_text(raw)


def build() -> pd.DataFrame:
    """Download (or read from cache) every document and write the index and texts."""
    ensure_dirs()
    defaults = settings()["release_time_defaults_et"]
    min_words = settings()["sample"]["min_speech_words"]
    docs = _fomc_documents(meetings()) + _speech_documents()
    rows = []
    for doc in tqdm(docs, desc="documents", disable=not sys.stderr.isatty()):
        row = {c: doc.get(c) for c in COLUMNS}
        try:
            raw = http.get(doc["url"])
        except FileNotFoundError:
            row["note"] = "404"
            rows.append(row)
            continue
        text, meta = _clean(doc, raw)
        if doc["doc_type"] != "speech":
            if meta.get("release_time_et"):
                row["release_time_et"], row["time_source"] = meta["release_time_et"], "document_text"
            else:
                row["release_time_et"], row["time_source"] = doc["default_time"], "default"
        elif row["release_time_et"] is None:
            row["release_time_et"], row["time_source"] = defaults["speech_no_time"], "default_no_time"
        row["info_start_et"] = doc.get("info_start_et") or row["release_time_et"]
        row["n_words"] = len(text.split())
        if doc["doc_type"] == "speech" and row["n_words"] < min_words:
            row["note"] = f"under {min_words} words"
        if row["release_date"] is None or pd.isna(row["release_date"]):
            row["note"] = "no release date"
        row["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        (INTERIM / "texts" / f"{doc['doc_id']}.txt").write_text(text)
        rows.append(row)
    index = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("doc_id")
    index.to_csv(INTERIM / "documents.csv", index=False)
    return index


def usable(index: pd.DataFrame | None = None) -> pd.DataFrame:
    """Documents that can be scored: text present, release date known, no exclusion note."""
    index = pd.read_csv(INTERIM / "documents.csv") if index is None else index
    return index[index["note"].isna() & index["n_words"].fillna(0).gt(0)].reset_index(drop=True)
