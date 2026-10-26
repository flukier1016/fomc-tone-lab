"""The Fed right now: policy rates and the Committee, assembled from public sources.

Rates: the effective federal funds rate (EFFR) and SOFR from the New York Fed's
reference-rate API, daily.

Committee: who votes this year, read from the attendance list of the latest
minutes (members, alternates, other presidents); which Reserve Bank each
president leads, read from the minutes' own "President of the Federal Reserve
Bank of ..." lines; dissents, read from the "Voting against" sentence of every
statement. Nothing is typed in by hand, so the page follows rotations and new
appointments by itself.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd

NYFED = "https://markets.newyorkfed.org/api/rates/{kind}/search.json?startDate={start}&endDate={end}"
_NAME = r"[A-Z][a-z]+(?: [A-Z]\.)? [A-Z][A-Za-z'\-]+"
_NAME_RE = re.compile(_NAME)
_PRESIDENT = re.compile(
    rf"({_NAME}), (First Vice President|President),? (?:of the )?Federal Reserve Bank of "
    r"([A-Z][A-Za-z. ]+?)(?=[,;.]| with| as|$)"
)
_AGAINST = re.compile(r"Voting against (?:this |the )?(?:monetary )?(?:policy )?action(?: was| were|:) ([^\n]+)")


# ------------------------------------------------------------------ rates
def policy_rates(start: str = "2018-01-01") -> pd.DataFrame:
    """Daily EFFR and SOFR in percent (refreshed on every call: the series grows each day)."""
    from . import http  # pipeline only: the hosted image has no requests

    end = date.today().isoformat()
    frames = []
    for kind, col in (("unsecured/effr", "effr"), ("secured/sofr", "sofr")):
        raw = http.get(NYFED.format(kind=kind, start=start, end=end), refresh=True)
        rows = json.loads(raw)["refRates"]
        frames.append(pd.Series({r["effectiveDate"]: r["percentRate"] for r in rows}, name=col))
    out = pd.concat(frames, axis=1).sort_index()
    out.index.name = "date"
    return out.reset_index()


# -------------------------------------------------------------- committee
def _names(text: str) -> list[str]:
    return _NAME_RE.findall(text)


def _banks(blocks: list[str]) -> dict[str, tuple[str, str]]:
    """name -> (title, bank) from 'X, President of the Federal Reserve Bank of Y' lines and 'respectively' lists."""
    out = {}
    for b in blocks:
        for name, title, bank in _PRESIDENT.findall(b):
            out[name] = (title, bank.strip())
        m = re.match(
            r"(.+), (?:Presidents|First Vice Presidents) of the Federal Reserve Banks of (.+), respectively", b
        )
        if m:
            names = _names(m.group(1))
            banks = [x.strip() for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(2)) if x.strip()]
            if len(names) == len(banks):
                out.update({n: ("President", bk) for n, bk in zip(names, banks)})
    return out


def committee(minutes: pd.DataFrame, speeches: pd.DataFrame) -> pd.DataFrame:
    """The Committee as of the latest minutes. `minutes`: doc_id, release_date, url (newest last);
    `speeches`: speaker, speaker_role, release_date (Board members' latest titles)."""
    from . import http, textclean  # pipeline only: reads the raw cache

    minutes = minutes.sort_values("release_date")
    blocks_by_doc = {}
    for m in minutes.tail(10).itertuples():  # a year of minutes covers the January assignment of votes
        try:
            blocks_by_doc[m.doc_id] = textclean.html_blocks(http.get(m.url))
        except FileNotFoundError:
            continue
    if not blocks_by_doc:
        return pd.DataFrame()
    banks = {}
    for blocks in blocks_by_doc.values():  # oldest to newest, so the latest title wins
        banks.update(_banks(blocks))
    latest = list(blocks_by_doc.values())[-1]
    at = next((i for i, b in enumerate(latest) if b.startswith("Attendance ")), None)
    if at is None:
        return pd.DataFrame()
    head = latest[at][len("Attendance ") :]
    chair = re.search(rf"({_NAME}), Chair(?:man)?\b", head)
    vice = re.search(rf"({_NAME}), Vice Chair\b", head)
    members = _names(re.sub(r", (?:Chairman|Chair|Vice Chair)\b", "", head))
    alternates = next((_names(b.split("Alternate Members")[0]) for b in latest[at:] if "Alternate Members" in b), [])
    others = next(
        (_names(b.split(", Presidents")[0]) for b in latest[at:] if "Presidents of the Federal Reserve Banks" in b), []
    )
    roles = speeches.sort_values("release_date").groupby("speaker")["speaker_role"].last().to_dict()
    rows = []
    for status, names in (("voter", members), ("alternate", alternates), ("non-voting", others)):
        for n in names:
            title, bank = banks.get(n, (None, None))
            board = bank is None
            role = (
                "Chair" if chair and n == chair.group(1) else roles.get(n, "Governor") if board else f"{title}, {bank}"
            )
            rows.append(
                {
                    "name": n,
                    "status": status,
                    "board": int(board),
                    "role": role,
                    "bank": bank,
                    "fomc_vice_chair": int(bool(vice and n == vice.group(1))),
                    "as_of": minutes.iloc[-1]["release_date"],
                }
            )
    return pd.DataFrame(rows).drop_duplicates("name")


def _groups(body: str) -> list[tuple[str, str]]:
    """'A and B, who preferred X; and C, who preferred Y.' -> [('A and B', 'preferred X'), ('C', 'preferred Y')]."""
    pieces = re.split(r",? who ", body)
    names, out = pieces[0], []
    for piece in pieces[1:]:
        later = re.search(rf"[,;] and ({_NAME}(?:,? (?:and )?{_NAME})*)$", piece)  # the next group's names
        clause = piece[: later.start()] if later else piece
        out.append((names, clause.split(". ")[0].rstrip(".")))  # not the sentence on absences that may follow
        if not later:
            break
        names = later.group(1)
    return out


def dissents(statements: pd.DataFrame) -> pd.DataFrame:
    """One row per dissenting vote: doc_id, date, name, what the dissenter preferred (hike, cut, hold or other)
    and the statement's own words for it."""
    rows = []
    for s in statements.itertuples():
        for m in _AGAINST.finditer(s.text or ""):
            for who, why in _groups(m.group(1)):
                pref = why.lower()
                direction = (
                    "hike"
                    if re.search(r"preferred to (raise|increase)", pref)
                    else "cut"
                    if re.search(r"preferred to (lower|reduce|cut)", pref)
                    else "hold"
                    if re.search(r"preferred to (maintain|keep|leave|hold)|preferred no change", pref)
                    else "other"
                )
                for name in _names(who):
                    rows.append(
                        {
                            "doc_id": s.doc_id,
                            "date": s.release_date,
                            "name": name,
                            "preferred": direction,
                            "reason": why,
                        }
                    )
    return pd.DataFrame(rows, columns=["doc_id", "date", "name", "preferred", "reason"])


# ------------------------------------------------------------------- bios
FOMC_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomc.htm"
BOARD_BIO = "https://www.federalreserve.gov/aboutthefed/bios/board/{last}.htm"
BANK_PAGE = "https://www.federalreserve.gov/aboutthefed/federal-reserve-system-{bank}.htm"
_DEGREE = re.compile(r"\b(?:BA|BS|AB|MA|MS|MBA|MPA|MPhil|JD|PhD)\b|(?i:\b(?:bachelor|master|doctorate|degree))")
_INITIAL = re.compile(r"\b([A-Z])\. (?=[A-Z])")  # "Robert P. Gwinn": a middle initial does not end a sentence


def bio_links() -> dict[str, str]:
    """Each member's page as the Fed's FOMC page links it (Board biographies, Reserve Bank pages)."""
    from bs4 import BeautifulSoup

    from . import http

    soup = BeautifulSoup(http.get(FOMC_PAGE, refresh=True), "lxml")
    out = {}
    for a in soup.select("a[href]"):
        name, href = a.get_text(" ", strip=True), a["href"]
        if _NAME_RE.fullmatch(name) and (
            "bios/board" in href or "federal-reserve-system-" in href or "orgchart" in href
        ):
            out[name] = href if href.startswith("http") else "https://www.federalreserve.gov" + href
    return out


def bio_sentences(html: bytes | str, name: str) -> dict[str, str]:
    """Up to four sentences in the Fed's own words: when the member took office, or joined the Board ("took"); a
    later title, such as Vice Chair ("role"); what came before ("before"); and the degrees ("school"). Verbatim, so
    nothing is paraphrased or remembered."""
    from bs4 import BeautifulSoup

    from .textutil import sentences

    last = name.split()[-1]
    paras = [" ".join(p.get_text(" ").split()) for p in BeautifulSoup(html, "lxml").select("p")]  # source line breaks
    sents = [
        s.replace("\x00", ".")
        for p in paras
        if last in p or "Prior to" in p or _DEGREE.search(p)
        for s in sentences(_INITIAL.sub("\\1\x00 ", p))
    ]
    office = r"took office|sworn in|became|serving as a member|served as a member"
    for pattern in (office, r"\bis the\b"):  # a first vice president's page says "is the"
        start = next((i for i, s in enumerate(sents) if last in s and re.search(pattern, s)), None)
        if start is not None:
            break
    else:
        return {}
    sents = sents[start:]  # the biography proper, after the page's navigation
    dated = re.compile(r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d")
    member = next((s for s in sents if "member of the Board" in s and re.search(office, s) and dated.search(s)), None)
    role = next(
        (s for s in sents if re.search(r"(?:took office|sworn in) as (?:the )?(?:\w+ )?(?:Vice Chair|[Cc]hair)", s)),
        None,
    )
    took = member or role or sents[0]
    before = next(
        (s for s in sents if re.match(r"(?:Prior to|Before|Previously|Most recently)", s) or "was previously" in s),
        None,
    )
    school = next(
        (s for s in sents if re.search(r"\b(?:received|earned|holds|graduated|has an?)\b", s) and _DEGREE.search(s)),
        None,
    )
    parts = (("took", took), ("role", role if role != took else None), ("before", before), ("school", school))
    return {k: v for k, v in parts if v}


def read_more(html: bytes | str, name: str) -> str | None:
    """The Reserve Bank's own page for its president, where the Board's page stops at "Read more"."""
    from bs4 import BeautifulSoup

    last = name.split()[-1].lower()
    for a in BeautifulSoup(html, "lxml").select("a[href]"):
        if a.get_text(strip=True).lower() == "read more" and last in a["href"].lower():
            return a["href"]
    return None


def bios(members: pd.DataFrame, previous: dict | None = None) -> dict[str, dict]:
    """Each member's sentences (see `bio_sentences`) with the pages they come from; a page that fails keeps last
    time's entry."""
    from . import http

    previous = previous or {}
    try:
        links = bio_links()
    except Exception:  # the FOMC page is down: keep what we had
        return previous
    by_last = {k.split()[-1]: v for k, v in links.items()}  # "Cheryl Venable" there, "Cheryl L. Venable" in the minutes
    out = {}
    for m in members.itertuples():
        last = m.name.split()[-1]
        bank = (m.bank if isinstance(m.bank, str) else "").lower().replace(".", "").replace(" ", "-")
        url = (
            links.get(m.name)
            or by_last.get(last)
            or (BOARD_BIO.format(last=last.lower()) if m.board else BANK_PAGE.format(bank=bank))
        )
        try:
            html = http.get(url)
            said = bio_sentences(html, m.name)
            if not said:  # a page cached before this member arrived
                html = http.get(url, refresh=True)
                said = bio_sentences(html, m.name)
            sources = [url]
            more = read_more(html, m.name) if said and not {"before", "school"} <= set(said) else None
            if more:
                extra = bio_sentences(http.get(more), m.name)
                if {"before", "school"} & (set(extra) - set(said)):
                    said = {
                        k: said.get(k) or extra[k]
                        for k in ("took", "role", "before", "school")
                        if k in said or k in extra
                    }
                    sources.append(more)
        except Exception:
            said = {}
        if said:
            out[m.name] = {**said, "sources": sources, "fetched": date.today().isoformat()}
        elif m.name in previous:
            out[m.name] = previous[m.name]
    return out
