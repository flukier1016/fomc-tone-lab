"""REST API over the SQLite store, plus the dashboard. Start with `fomc serve`.

Local use: binds to 127.0.0.1; the Settings endpoints can write your API key to .env.
Hosted use (Railway etc.): set FOMC_PUBLIC=1 for a read-only deployment. Optional:
  FOMC_BASIC_AUTH=user:password   require a login for every page and endpoint
  FOMC_SCORE_TOKEN=...            allow live scoring with the server's ANTHROPIC_API_KEY
                                  only for requests that send this token
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, db, duration, provenance
from .config import settings
from .llm import provider

WEB = Path(__file__).parent / "web"
ROLLING = {"statement": 5, "minutes": 5, "presser": 5, "speech": 25}
PUBLIC = os.environ.get("FOMC_PUBLIC") == "1"
BASIC_AUTH = os.environ.get("FOMC_BASIC_AUTH", "")
SCORE_TOKEN = os.environ.get("FOMC_SCORE_TOKEN", "")


@asynccontextmanager
async def lifespan(_app):
    con = db.connect()
    db.init(con)  # schema and migrations once at startup, not on every request
    con.close()
    yield


app = FastAPI(
    title="FOMC Tone & Duration",
    version=__version__,
    description="Fed communication tone, Treasury yields and duration positioning.",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError):
    # Nonstandard JSON numbers (NaN/Infinity) must produce a validation response,
    # not another serialization error while reporting the original invalid input.
    return JSONResponse(status_code=422, content=jsonable({"detail": jsonable_encoder(exc.errors())}))


@app.middleware("http")
async def guard(request: Request, call_next):
    """Optional login for hosted deployments, plus conservative security headers."""
    if BASIC_AUTH and request.url.path != "/api/health":
        expected = "Basic " + base64.b64encode(BASIC_AUTH.encode()).decode()
        if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            return JSONResponse(
                {"detail": "login required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="FOMC Tone Lab"'},
            )
    tag = _etag(request)
    if tag and request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})
    response = await call_next(request)
    if tag and response.status_code == 200:
        response.headers["ETag"] = tag
        response.headers["Cache-Control"] = "no-cache"  # revalidate every time; unchanged data costs a 304
    if request.url.path.startswith("/static/"):
        # a fingerprinted URL never changes; anything else (screens, the chart library) is checked against its ETag,
        # so a returning visitor sees a replaced image at once instead of a heuristically cached one
        fingerprinted = "v=" in request.url.query
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if fingerprinted else "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


_NO_ETAG = {"/api/health", "/api/settings", "/api/labels/next"}
_BOOT = time.time_ns()  # a restart (new code) invalidates every validator


def _etag(request: Request) -> str | None:
    """A validator for read-only API responses: it changes when the store, the code or the date does."""
    import hashlib

    path = request.url.path
    if request.method != "GET" or not (path.startswith("/api/") or path == "/feed.xml") or path in _NO_ETAG:
        return None
    stamp = "|".join(
        str(f.stat().st_mtime_ns) if f.exists() else "-"
        for f in (db.DB_PATH, db.DB_PATH.with_name(db.DB_PATH.name + "-wal"))
    )
    key = f"{path}?{request.url.query}|{stamp}|{date.today()}|{__version__}|{PUBLIC}|{_BOOT}"
    return 'W/"' + hashlib.sha1(key.encode()).hexdigest()[:20] + '"'


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def jsonable(obj):
    """Plain JSON: NaN becomes null, numpy scalars become Python numbers."""
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "item"):
        obj = obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _methods(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT DISTINCT method FROM scores ORDER BY method")]


RELEVANT = "coalesce(json_extract(s.details, '$.policy_relevance'), '') != 'low'"  # as the research reads Claude


def mean_pct(series: pd.Series, k: int, value: float) -> float:
    """Percentile of an average of k documents among every run of k consecutive documents: like for like, since an
    average is less extreme than a single document."""
    ref = series.rolling(k).mean().dropna()
    return float((ref < value).mean() * 100) if len(ref) else float("nan")


def _recent_tone(own: pd.DataFrame, pool: pd.Series, today: date) -> tuple[float | None, int]:
    """A member's last ten relevant speeches of the past two years (`own`: release_date, score with low-relevance
    speeches blank), their average as a percentile of every run of as many Board speeches (`pool`)."""
    from datetime import timedelta

    scored = own[own["release_date"] >= (today - timedelta(days=730)).isoformat()]["score"].dropna().tail(10)
    pct = mean_pct(pool, len(scored), scored.mean()) if len(scored) >= 3 and len(pool) else None
    return pct, int(len(scored))


def _default_method(con) -> str | None:
    """Claude's level score once it covers most of the corpus (not after an 8-document pilot), else TF-IDF."""
    counts = dict(con.execute("SELECT method, count(*) FROM scores GROUP BY method").fetchall())
    docs = con.execute("SELECT count(*) FROM documents WHERE note IS NULL").fetchone()[0] or 1
    llm = sorted((m for m in counts if m.startswith("llm:") and counts[m] >= 0.8 * docs), key=lambda m: -counts[m])
    if llm:
        return llm[0]
    return "supervised" if "supervised" in counts else (next(iter(sorted(counts)), None))


# ------------------------------------------------------------------ pages
def _asset_version() -> str:
    """Content hash of the front-end files: asset URLs change exactly when the files do."""
    import hashlib

    h = hashlib.sha1()
    for name in ("index.html", "styles.css", "app.js", "vendor/icons/sprite.svg"):
        h.update((WEB / name).read_bytes())
    return h.hexdigest()[:10]


_INDEX = {"version": None, "html": ""}


@app.get("/", include_in_schema=False)
def index():
    version = _asset_version()
    if _INDEX["version"] != version:
        sprite = (WEB / "vendor/icons/sprite.svg").read_text()
        html = (WEB / "index.html").read_text().replace("__V__", version).replace("__SPRITE__", sprite)
        _INDEX.update(version=version, html=html)
    return HTMLResponse(_INDEX["html"], headers={"Cache-Control": "no-cache"})


@app.get("/story", include_in_schema=False)
def story_page(s: int | None = None, deck: str | None = None):
    """The deck at its own address, apart from the dashboard: /story opens it, /story?s=5 on the fifth slide,
    /story?deck=technical the technical appendix."""
    params = "&".join(p for p in (f"deck={deck}" if deck == "technical" else "", f"s={s}" if s else "") if p)
    return RedirectResponse("/#/story" + (f"?{params}" if params else ""))


FEED_TYPES = {"statement": "Statement", "minutes": "Minutes", "presser": "Press conference", "speech": "Speech"}
FEED_PLURAL = {"statement": "statements", "minutes": "minutes", "presser": "press conferences", "speech": "speeches"}
FEED_SHIFT = {
    2: "a clear hawkish turn",
    1: "more hawkish",
    0: "no material change",
    -1: "more dovish",
    -2: "a clear dovish turn",
}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


@app.get("/feed.xml", include_in_schema=False)
def feed(request: Request, con=Depends(get_con)):
    """An Atom feed of the latest policy documents as Claude reads them: subscribe in any feed reader (or have one
    forward it by email). Each entry gives the lean, the percentile against every earlier document of its type and
    the Fed's own words behind it; the words "hawkish", "dovish" and "balanced" follow the Home page (score beyond
    plus or minus 0.15)."""
    from xml.etree import ElementTree as ET
    from zoneinfo import ZoneInfo

    method = _default_method(con) or ""
    df = db.query(
        con,
        "SELECT d.doc_id, d.doc_type, d.meeting_date, d.release_date, d.release_time_et, d.title, d.speaker, d.url, "
        "s.score "
        f"FROM scores s JOIN documents d ON d.doc_id = s.doc_id WHERE s.method = ? AND d.note IS NULL AND {RELEVANT} "
        "ORDER BY d.release_date, coalesce(d.release_time_et, ''), d.doc_id",
        (method,),
    )
    # percentile against every earlier document of the same type: what a reader could have known that day
    df["pct"] = df.groupby("doc_type")["score"].transform(
        lambda x: [float((x.iloc[:i] < v).mean() * 100) if i else np.nan for i, v in enumerate(x)]
    )
    latest = df.tail(40).iloc[::-1]
    quotes: dict[str, list[str]] = {}
    _, model, rubric = (method.split(":") + ["", "", ""])[:3]  # llm:<model>:<rubric version>
    for key, parsed in con.execute(
        "SELECT key, parsed FROM llm_records WHERE mode = 'level' AND status = 'ok' AND coalesce(run_tag, '') = '' "
        f"AND model = ? AND rubric_version = ? AND key IN ({','.join('?' * len(latest))})",
        (model, rubric, *latest["doc_id"]),
    ):
        quotes[key] = [e["quote"] for e in (json.loads(parsed).get("evidence") or [])][:2]
    shifts: dict[str, tuple[int, str]] = {}  # a statement against the previous decision: what moves the curve (H2)
    for key, parsed in con.execute(
        "SELECT key, parsed FROM llm_records WHERE mode = 'shift' AND status = 'ok' AND coalesce(run_tag, '') = '' "
        f"AND model = ? AND rubric_version = ? AND key IN ({','.join('?' * len(latest))})",
        (model, rubric, *latest["doc_id"]),
    ):
        p = json.loads(parsed)
        shifts[key] = (int(p["shift_score"]), p.get("rationale") or "")
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    base = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{host}"
    eastern = ZoneInfo("America/New_York")

    def stamp(r) -> str:
        hh, mm = (r.release_time_et or "14:00").split(":")[:2]
        y, m, d = map(int, r.release_date.split("-"))
        return datetime(y, m, d, int(hh), int(mm), tzinfo=eastern).isoformat()

    atom = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    ET.SubElement(atom, "title").text = "FOMC Tone Lab: the Fed, read by Claude"
    ET.SubElement(atom, "subtitle").text = (
        "Every new statement, set of minutes, press conference and policy speech, with Claude's hawkish or dovish "
        "reading, its percentile in history and the Fed's own words behind it."
    )
    ET.SubElement(atom, "id").text = f"{base}/"
    ET.SubElement(atom, "link", rel="self", href=f"{base}/feed.xml")
    ET.SubElement(atom, "link", rel="alternate", href=f"{base}/")
    ET.SubElement(atom, "updated").text = (
        stamp(latest.iloc[0]) if len(latest) else date.today().isoformat() + "T00:00:00Z"
    )
    ET.SubElement(ET.SubElement(atom, "author"), "name").text = "FOMC Tone Lab"
    for r in latest.itertuples():
        lean = "hawkish" if r.score > 0.15 else "dovish" if r.score < -0.15 else "balanced"
        when = date.fromisoformat(r.release_date).strftime("%-d %B %Y")
        kind = FEED_TYPES.get(r.doc_type, r.doc_type)
        who = f" by {r.speaker}" if r.doc_type == "speech" and r.speaker else ""
        pct = (
            ""
            if np.isnan(r.pct)
            else f", {_ordinal(int(round(r.pct)))} percentile of earlier {FEED_PLURAL[r.doc_type]}"
        )
        link = f"{base}/#/documents?doc={r.doc_id}"
        entry = ET.SubElement(atom, "entry")
        if r.doc_type == "minutes" and r.meeting_date:
            kind = f"Minutes of the {date.fromisoformat(r.meeting_date):%-d %B} meeting"
        turn = f"; against the last decision, {FEED_SHIFT[shifts[r.doc_id][0]]}" if r.doc_id in shifts else ""
        ET.SubElement(entry, "title").text = f"{kind}{who}, {when}: {lean} ({r.score:+.2f}{pct}){turn}"
        ET.SubElement(entry, "id").text = link
        ET.SubElement(entry, "link", rel="alternate", href=link)
        ET.SubElement(entry, "updated").text = stamp(r)
        ET.SubElement(entry, "category", term=r.doc_type, label=FEED_TYPES.get(r.doc_type, r.doc_type))
        body = f"<p>{_html(shifts[r.doc_id][1])}</p>" if shifts.get(r.doc_id, (0, ""))[1] else ""
        body += "".join(f"<blockquote>{_html(q)}</blockquote>" for q in quotes.get(r.doc_id, []))
        if r.title and r.doc_type == "speech":
            body = f"<p><b>{_html(r.title)}</b></p>" + body
        body += f'<p><a href="{link}">Claude\'s full reading and evidence</a>'
        body += f' &middot; <a href="{_html(r.url)}">the Fed\'s page</a></p>' if r.url else "</p>"
        ET.SubElement(entry, "content", type="html").text = body
    xml = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(atom, encoding="utf-8")
    return Response(xml, media_type="application/atom+xml; charset=utf-8")


def _html(text: str) -> str:
    return escape(text or "", quote=True)


@app.get("/api/health", include_in_schema=False)
def health(con=Depends(get_con)):
    n = con.execute("SELECT count(*) FROM documents WHERE note IS NULL").fetchone()[0]
    return {"status": "ok", "documents": n, "public": PUBLIC, "version": __version__}


def _next_meeting(con) -> dict | None:
    row = con.execute("SELECT value FROM meta WHERE key = 'upcoming_meetings'").fetchone()
    if not row:
        return None
    today = date.today().isoformat()
    upcoming = sorted(d for d in json.loads(row[0]) if d >= today)
    if not upcoming:
        return None
    return {"date": upcoming[0], "days": (date.fromisoformat(upcoming[0]) - date.today()).days}


@app.get("/api/pulse")
def pulse(con=Depends(get_con)):
    """The Home page's Fed pulse: latest reading per document type, the market now, the next decision."""
    method = _default_method(con)
    readings = []
    for t in ("statement", "minutes", "presser", "speech"):
        df = db.query(
            con,
            "SELECT d.doc_id, d.release_date, d.title, d.speaker, s.score FROM scores s "
            f"JOIN documents d ON d.doc_id = s.doc_id WHERE s.method = ? AND d.doc_type = ? AND {RELEVANT} "
            "ORDER BY d.release_date, d.doc_id",
            (method or "", t),
        )
        if len(df) < 13:
            continue
        last = df.iloc[-1]
        if t == "speech":
            pct = mean_pct(df["score"].iloc[:-1], 25, df["score"].iloc[-25:].mean())
        else:
            pct = float((df["score"].iloc[:-1] < last["score"]).mean() * 100)
        readings.append(
            {
                "doc_type": t,
                "doc_id": last["doc_id"],
                "date": last["release_date"],
                "title": last["title"],
                "speaker": last["speaker"],
                "score": float(last["score"]),
                "percentile": pct,
                "basis": "average of the latest 25 speeches" if t == "speech" else "latest document",
            }
        )
    y = db.query(con, "SELECT date, t2y, t10y FROM yields WHERE t2y IS NOT NULL ORDER BY date DESC LIMIT 130")
    market = None
    if len(y) > 22:
        y = y.iloc[::-1].reset_index(drop=True)
        cur, month = y.iloc[-1], y.iloc[-22]
        market = {
            "date": cur["date"],
            "t2y": cur["t2y"],
            "t10y": cur["t10y"],
            "slope_bp": 100 * (cur["t10y"] - cur["t2y"]),
            "d2y_1m_bp": 100 * (cur["t2y"] - month["t2y"]),
            "d10y_1m_bp": 100 * (cur["t10y"] - month["t10y"]),
            "spark": records(y[["date", "t2y", "t10y"]]),
        }
    minutes = next((r for r in readings if r["doc_type"] == "minutes"), None)
    mood = None
    if minutes:
        p = minutes["percentile"]
        mood = "hawkish" if p >= 60 else "dovish" if p <= 40 else "balanced"
    return {"method": method, "readings": readings, "market": market, "mood": mood, "next_meeting": _next_meeting(con)}


# --------------------------------------------------------------- overview
@app.get("/api/overview")
def overview(con=Depends(get_con)):
    docs = db.query(
        con,
        "SELECT doc_type, count(*) AS n, min(release_date) AS first, max(release_date) AS last, "
        "sum(n_words) AS words FROM documents WHERE note IS NULL GROUP BY doc_type",
    )
    methods = db.query(con, "SELECT method, count(*) AS n FROM scores GROUP BY method ORDER BY method")
    last_yield = db.query(con, "SELECT * FROM yields ORDER BY date DESC LIMIT 1")
    spend = con.execute("SELECT coalesce(sum(cost_usd), 0), count(*) FROM llm_records").fetchone()
    latest = db.query(  # the newest documents about policy: speeches Claude reads as off-topic are left out
        con,
        "SELECT d.doc_id, d.doc_type, d.release_date, d.speaker, d.title, s.score, "
        "json_extract(s.details, '$.policy_relevance') AS relevance FROM documents d "
        "LEFT JOIN scores s ON s.doc_id = d.doc_id AND s.method = ? "
        f"WHERE d.note IS NULL AND {RELEVANT} ORDER BY d.release_date DESC, d.doc_id LIMIT 6",
        (_default_method(con) or "",),
    )
    return {
        "next_meeting": _next_meeting(con),
        "public": PUBLIC,
        "documents": records(docs),
        "methods": records(methods),
        "last_yield": records(last_yield)[0] if len(last_yield) else None,
        "llm": {**_status(), "spend_usd": spend[0], "records": spend[1]},
        "latest": records(latest),
        "default_method": _default_method(con),
        "version": __version__,
    }


# -------------------------------------------------------------- documents
def _fts_query(q: str) -> str:
    """The search box's syntax as an FTS5 query, every term quoted so FTS5 syntax cannot break it: words must all
    appear, "exact phrases", a bare OR between terms, -word or NOT word to leave documents out, word* for a prefix.
    Exclusions are applied to the whole of what is included, and need something to include."""
    keep, drop, pending = [], [], False
    for t in re.findall(r'-?"[^"]+"\*?|\S+', q):
        if t == "NOT":
            pending = True
            continue
        if t == "OR":
            if keep and keep[-1] != "OR":
                keep.append("OR")
            continue
        negate = pending or (t.startswith("-") and len(t) > 1)
        pending = False
        t = t[1:] if t.startswith("-") and len(t) > 1 else t
        prefix = t.endswith("*") and len(t) > 1
        word = t.rstrip("*").replace('"', "").strip()
        if not word:
            continue
        term = f'"{word}"' + ("*" if prefix else "")
        (drop if negate else keep).append(term)
    while keep and keep[-1] == "OR":
        keep.pop()
    if not keep:
        if drop:
            raise HTTPException(400, "Add a word to search for: -word and NOT word only leave documents out.")
        return '""'
    query = " ".join(keep)
    return f"({query})" + "".join(f" NOT {t}" for t in drop) if drop else query


@app.get("/api/documents")
def documents(
    types: str = "",
    q: str = "",
    speaker: str = "",
    start: str = "",
    end: str = "",
    method: str = "",
    limit: int = Query(50, le=500),
    offset: int = 0,
    mode: str = Query("list", pattern="^(list|scatter)$"),
    con=Depends(get_con),
):
    method = method or _default_method(con) or ""
    where, params = ["d.note IS NULL"], []
    if types:
        tl = [t for t in types.split(",") if t]
        where.append(f"d.doc_type IN ({','.join('?' * len(tl))})")
        params += tl
    if speaker:
        where.append("d.speaker LIKE ?")
        params.append(f"%{speaker}%")
    if start:
        where.append("d.release_date >= ?")
        params.append(start)
    if end:
        where.append("d.release_date <= ?")
        params.append(end)
    base = (
        "FROM documents d LEFT JOIN scores s ON s.doc_id = d.doc_id AND s.method = ? "
        "LEFT JOIN events e ON e.doc_id = d.doc_id"
    )
    select = (
        "SELECT d.doc_id, d.doc_type, d.release_date, d.release_time_et, d.speaker, d.speaker_role, "
        "d.title, d.n_words, s.score, e.d2y_bp, e.d10y_bp, "
        "coalesce(json_extract(s.details, '$.policy_relevance'), '') AS relevance"
    )
    if q:
        base += " JOIN documents_fts f ON f.rowid = d.rowid"
        where.append("documents_fts MATCH ?")
        select += ", snippet(documents_fts, 2, '<mark>', '</mark>', ' ... ', 16) AS snippet"
        params.append(_fts_query(q))
        order = "ORDER BY f.rank"
    else:
        order = "ORDER BY d.release_date DESC, d.doc_id"
    sql_where = " WHERE " + " AND ".join(where)
    try:
        total = con.execute(f"SELECT count(*) {base}{sql_where}", [method, *params]).fetchone()[0]
        if mode == "scatter":
            # the timeline summarizes tone as the research reads it: Claude's low-relevance readings left out
            rows = db.query(
                con,
                f"SELECT d.doc_id, d.doc_type, d.release_date, CASE WHEN {RELEVANT} THEN s.score END AS score "
                f"{base}{sql_where} ORDER BY d.release_date, d.doc_id",
                tuple([method, *params]),
            )
            low = con.execute(
                f"SELECT count(*) {base}{sql_where} AND s.score IS NOT NULL AND NOT ({RELEVANT})", [method, *params]
            ).fetchone()[0]
            return {"total": total, "method": method, "items": records(rows), "low_relevance": low}
        else:
            rows = db.query(
                con, f"{select} {base}{sql_where} {order} LIMIT ? OFFSET ?", tuple([method, *params, limit, offset])
            )
    except sqlite3.OperationalError as exc:
        raise HTTPException(400, f"search error: {exc}") from exc
    return {"total": total, "method": method, "items": records(rows)}


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, con=Depends(get_con)):
    doc = db.query(con, "SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
    if doc.empty:
        raise HTTPException(404, "document not found")
    scores = db.query(con, "SELECT method, score, details FROM scores WHERE doc_id = ?", (doc_id,))
    scores["details"] = scores["details"].map(lambda d: json.loads(d) if d else {})
    event = db.query(con, "SELECT * FROM events WHERE doc_id = ?", (doc_id,))
    llm = db.query(
        con,
        "SELECT model, mode, status, parsed, evidence_share, created_at, cost_usd "
        "FROM llm_records WHERE key = ? AND mode IN ('level', 'shift') AND coalesce(run_tag, '') = '' "
        "ORDER BY created_at DESC",  # the main run; repeat runs (r2, ...) are for the stability check
        (doc_id,),
    )
    llm["parsed"] = llm["parsed"].map(lambda p: json.loads(p) if p else None)
    spans = []
    level = next((p for m, p in zip(llm["mode"], llm["parsed"]) if m == "level" and p), None)
    if level:
        from .llm.scorer import verify_quotes

        spans = verify_quotes([e["quote"] for e in level.get("evidence", [])], doc["text"].iloc[0] or "")["spans"]
    decision = db.query(con, "SELECT * FROM decisions WHERE doc_id = ?", (doc_id,))
    from . import dictionary

    return {
        "dictionary_spans": dictionary.spans(doc["text"].iloc[0] or ""),  # what word counts see, for the reader
        "document": records(doc)[0],
        "scores": records(scores),
        "event": records(event)[0] if len(event) else None,
        "decision": records(decision)[0] if len(decision) else None,
        "llm": records(llm),
        "evidence_spans": spans,
    }


@app.get("/api/documents/{doc_id}/diff")
def document_diff(doc_id: str, con=Depends(get_con)):
    """Word-level redline of a statement against the previous policy decision."""
    from . import policy

    row = con.execute("SELECT prev_doc_id FROM decisions WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None or row[0] is None:
        raise HTTPException(404, "no previous decision to compare with")
    texts = dict(con.execute("SELECT doc_id, text FROM documents WHERE doc_id IN (?, ?)", (row[0], doc_id)).fetchall())
    segments, stats = policy.diff(texts.get(row[0], ""), texts.get(doc_id, ""))
    prev = con.execute("SELECT release_date FROM documents WHERE doc_id = ?", (row[0],)).fetchone()
    return {
        "doc_id": doc_id,
        "prev_doc_id": row[0],
        "prev_date": prev[0] if prev else None,
        **stats,
        "segments": segments,
    }


# ------------------------------------------------------------ time series
@app.get("/api/index")
def tone_index(method: str = "", types: str = "statement,minutes,presser,speech", con=Depends(get_con)):
    method = method or _default_method(con) or ""
    out = {}
    for t in [t for t in types.split(",") if t]:
        df = db.query(
            con,
            "SELECT d.release_date AS date, d.doc_id, s.score FROM scores s "
            "JOIN documents d ON d.doc_id = s.doc_id WHERE s.method = ? AND d.doc_type = ? "
            "ORDER BY d.release_date",
            (method, t),
        )
        if len(df):
            df["smooth"] = df["score"].rolling(ROLLING[t], min_periods=2).median()
        out[t] = records(df)
    return {"method": method, "series": out}


@app.get("/api/yields")
def yields(start: str = "2009-01-01", con=Depends(get_con)):
    return records(db.query(con, "SELECT date, t3m, t2y, t10y FROM yields WHERE date >= ? ORDER BY date", (start,)))


@app.get("/api/methods")
def methods(con=Depends(get_con)):
    return records(db.query(con, "SELECT method, count(*) AS n FROM scores GROUP BY method ORDER BY method"))


# ---------------------------------------------------------------- results
@app.get("/api/event-study")
def event_study(outcome: str = "", sample: str = "", control: str = "", con=Depends(get_con)):
    where, params = [], []
    for col, val in (("outcome", outcome), ("sample", sample), ("control", control)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    sql = "SELECT * FROM event_study" + (" WHERE " + " AND ".join(where) if where else "")
    return records(db.query(con, sql + " ORDER BY doc_type, method, regressor", tuple(params)))


@app.get("/api/event-curves")
def event_curves(doc_type: str, method: str, regressor: str = "level", con=Depends(get_con)):
    """Average cumulative 2-year move around releases, by tercile of tone."""
    df = db.query(
        con,
        "SELECT bucket, day, mean_bp, se_bp, n FROM event_curves WHERE doc_type = ? AND method = ? "
        "AND regressor = ? ORDER BY bucket, day",
        (doc_type, method, regressor),
    )
    return {b: records(g.drop(columns="bucket")) for b, g in df.groupby("bucket")}


# --------------------------------------------------------------- fed now
@app.get("/api/fed")
def fed_now(con=Depends(get_con)):
    """Policy rates, the latest decision and the Committee: who votes, who dissented, how they sound."""
    from datetime import timedelta

    from . import fed
    from . import members as member_history

    method = _default_method(con) or ""
    today = date.today()
    since = (today - timedelta(days=3 * 365)).isoformat()
    year_ago = (today - timedelta(days=365)).isoformat()
    dec = db.query(con, "SELECT * FROM decisions WHERE action IS NOT NULL ORDER BY release_date")
    rates = db.query(con, "SELECT date, effr, sofr FROM policy_rates WHERE date >= ? ORDER BY date", (since,))
    ylds = db.query(con, "SELECT date, t3m, t2y, t10y FROM yields WHERE date >= ? ORDER BY date", (since,))
    statements = db.query(
        con, "SELECT doc_id, release_date, text FROM documents WHERE doc_type = 'statement' ORDER BY release_date"
    )
    votes = fed.dissents(statements)
    actions = dict(zip(dec["doc_id"], dec["action"]))
    votes["lean"] = [
        member_history.lean(p, actions.get(d), why)
        for p, d, why in zip(votes["preferred"], votes["doc_id"], votes["reason"])
    ]
    votes["label"] = [member_history.dissent_label(p, why) for p, why in zip(votes["preferred"], votes["reason"])]
    members = db.query(con, "SELECT * FROM committee")
    sp = db.query(
        con,
        "SELECT d.doc_id, d.speaker, d.release_date, d.title, s.score FROM documents d "
        f"LEFT JOIN scores s ON s.doc_id = d.doc_id AND s.method = ? AND {RELEVANT} "
        "WHERE d.doc_type = 'speech' AND d.note IS NULL ORDER BY d.release_date",
        (method,),
    )
    pool = sp["score"].dropna()
    row = con.execute("SELECT value FROM meta WHERE key = 'bios'").fetchone()
    bios = json.loads(row[0]) if row else {}
    people = []
    for m in members.itertuples():
        own = sp[sp["speaker"] == m.name]
        tone_pct, tone_n = _recent_tone(own, pool, today)
        bio = bios.get(m.name) or {}
        mine = votes[votes["name"] == m.name]
        last_d = mine.iloc[-1] if len(mine) else None
        last_s = own.iloc[-1] if len(own) else None
        people.append(
            {
                "name": m.name,
                "status": m.status,
                "board": bool(m.board),
                "role": m.role,
                "bank": m.bank,
                "fomc_vice_chair": bool(m.fomc_vice_chair),
                "speeches_12m": int((own["release_date"] >= year_ago).sum()),
                "last_speech": None
                if last_s is None
                else {"doc_id": last_s["doc_id"], "date": last_s["release_date"], "title": last_s["title"]},
                "tone_pct": tone_pct,
                "tone_n": tone_n,
                "background": bio.get("before") or bio.get("took"),
                "took_office": member_history.took_office(bio.get("took")),
                "office": member_history.office(bio.get("took")),
                "dissents_12m": int((mine["date"] >= year_ago).sum()),
                "dissents_total": int(len(mine)),
                "last_dissent": None
                if last_d is None
                else {
                    "date": last_d["date"],
                    "preferred": last_d["preferred"],
                    "label": last_d["label"],
                    "lean": int(last_d["lean"]),
                    "doc_id": last_d["doc_id"],
                },
            }
        )
    order = {"voter": 0, "alternate": 1, "non-voting": 2}
    people.sort(
        key=lambda p: (
            order.get(p["status"], 3),
            p["role"] != "Chair",
            not p["fomc_vice_chair"],
            not p["board"],
            p["name"].split()[-1],
        )
    )
    current = last_move = None
    if len(dec):
        last = dec.iloc[-1]
        n_voters = int((members["status"] == "voter").sum()) or 12
        against = int((votes["doc_id"] == last["doc_id"]).sum())
        holds = 0
        for act in dec["action"].iloc[::-1]:
            if act != 0:
                break
            holds += 1
        moves = dec[dec["action"] != 0]
        current = {
            "doc_id": last["doc_id"],
            "date": last["release_date"],
            "action": int(last["action"]),
            "change_bp": None if pd.isna(last["change_bp"]) else int(last["change_bp"]),
            "range_low": float(last["range_low"]),
            "range_high": float(last["range_high"]),
            "vote": f"{n_voters - against}\u2013{against}",
            "holds_in_a_row": holds,
        }
        if len(moves):
            mv = moves.iloc[-1]
            last_move = {
                "date": mv["release_date"],
                "change_bp": None if pd.isna(mv["change_bp"]) else int(mv["change_bp"]),
            }
    eff = rates.dropna(subset=["effr"]).iloc[-1] if len(rates.dropna(subset=["effr"])) else None
    y_last = ylds.dropna(subset=["t2y"]).iloc[-1] if len(ylds) else None
    recent = votes[votes["date"] >= (today - timedelta(days=2 * 365)).isoformat()].iloc[::-1]
    return jsonable(
        {
            "method": method,
            "current": current,
            "last_move": last_move,
            "next_meeting": _next_meeting(con),
            "effr": None if eff is None else {"date": eff["date"], "effr": eff["effr"], "sofr": eff["sofr"]},
            "market": None
            if y_last is None
            else {
                "date": y_last["date"],
                "t3m": y_last["t3m"],
                "t2y": y_last["t2y"],
                "t10y": y_last["t10y"],
                "t2y_minus_effr_bp": None if eff is None else round(100 * (y_last["t2y"] - eff["effr"])),
            },
            "path": records(
                dec[dec["release_date"] >= since][["release_date", "range_low", "range_high", "change_bp", "doc_id"]]
            ),
            "range_before": records(
                dec[dec["release_date"] < since].tail(1)[["release_date", "range_low", "range_high"]]
            ),
            "rates": records(rates),
            "yields": records(ylds[["date", "t2y"]]),
            "members": people,
            "dissents": records(recent),
            "as_of": members["as_of"].iloc[0] if len(members) else None,
        }
    )


@app.get("/api/member")
def member(name: str, con=Depends(get_con)):
    """One member over time: the Fed's own sentences about them, every speech with its tone, the titles held, the
    dissents, the stretches of steady tone (see `members.py`) and what changed."""
    from . import fed
    from . import members as member_history

    row = db.query(con, "SELECT * FROM committee WHERE name = ?", (name,))
    if not len(row):
        raise HTTPException(404, f"{name} is not on the Committee")
    m = row.iloc[0]
    method = _default_method(con) or ""
    sp = db.query(
        con,
        "SELECT d.doc_id, d.speaker, d.release_date, d.title, d.speaker_role AS role, s.score, "
        "json_extract(s.details, '$.policy_relevance') AS relevance FROM documents d "
        "LEFT JOIN scores s ON s.doc_id = d.doc_id AND s.method = ? "
        "WHERE d.doc_type = 'speech' AND d.note IS NULL ORDER BY d.release_date, d.doc_id",
        (method,),
    )
    relevant = sp["relevance"].fillna("") != "low"
    pool = sp.loc[relevant, "score"].dropna()
    own = sp[sp["speaker"] == name]
    tone_pct, tone_n = _recent_tone(own.assign(score=own["score"].where(relevant)), pool, date.today())
    own = own.rename(columns={"release_date": "date"})
    read = own[own["score"].notna() & (own["relevance"].fillna("") != "low")]
    statements = db.query(
        con, "SELECT doc_id, release_date, text FROM documents WHERE doc_type = 'statement' ORDER BY release_date"
    )
    votes = fed.dissents(statements)
    mine = votes[votes["name"] == name]
    meta = con.execute("SELECT value FROM meta WHERE key = 'bios'").fetchone()
    bio = (json.loads(meta[0]) if meta else {}).get(name)
    dated = member_history.offices(bio)
    spells = member_history.role_spells(own)
    stretches = member_history.regimes(read["date"].tolist(), read["score"].tolist())
    dec = db.query(
        con,
        "SELECT release_date AS date, action, change_bp, range_low, range_high, doc_id FROM decisions "
        "WHERE action IS NOT NULL ORDER BY release_date",
    )
    return jsonable(
        {
            "name": m["name"],
            "status": m["status"],
            "board": bool(m["board"]),
            "role": m["role"],
            "bank": m["bank"],
            "fomc_vice_chair": bool(m["fomc_vice_chair"]),
            "as_of": m["as_of"],
            "method": method,
            "bio": bio,
            "took_office": dated[0]["date"] if dated else None,
            "office": dated[0]["office"] if dated else None,
            "tone_pct": tone_pct,
            "tone_n": tone_n,
            "speeches": records(own[["doc_id", "date", "title", "role", "score", "relevance"]]),
            "roles": spells,
            "regimes": stretches,
            "dissents": records(mine[["doc_id", "date", "preferred"]]),
            "decisions": records(dec),
            "events": member_history.events(
                own, spells, stretches, mine, dated, dict(zip(dec["doc_id"], dec["action"].astype(int)))
            ),
        }
    )


# ------------------------------------------------------------------ story
@app.get("/api/story")
def story(deck: str = "main", con=Depends(get_con)):
    """The deck, built from the store on every request: the Story page and `fomc slides` both read this.
    The default integrates introduction, methods and implementation; deck=technical is a legacy view."""
    from . import story as story_module

    if deck not in ("main", "technical"):
        raise HTTPException(404, "no such deck: main or technical")
    return jsonable(story_module.build(con, deck))


# ----------------------------------------------------------------- tracker
@app.get("/api/tracker")
def tracker(con=Depends(get_con)):
    """Every policy decision since 2009: target range, the move, how much the wording changed, the market."""
    method = _default_method(con) or ""
    df = db.query(
        con,
        "SELECT c.*, s.score, e.d2y_bp, e.d10y_bp FROM decisions c "
        "LEFT JOIN scores s ON s.doc_id = c.doc_id AND s.method = ? "
        "LEFT JOIN events e ON e.doc_id = c.doc_id WHERE c.action IS NOT NULL ORDER BY c.release_date",
        (method,),
    )
    if df.empty:
        return {"method": method, "decisions": [], "current": None}
    last = df.iloc[-1]
    holds = 0
    for act in df["action"].iloc[::-1]:
        if act != 0:
            break
        holds += 1
    moves = df[df["action"] != 0]
    since = df[df["release_date"] > f"{int(last['release_date'][:4]) - 1}{last['release_date'][4:]}"]
    current = {
        "doc_id": last["doc_id"],
        "date": last["release_date"],
        "action": int(last["action"]),
        "change_bp": None if pd.isna(last["change_bp"]) else int(last["change_bp"]),
        "range_low": last["range_low"],
        "range_high": last["range_high"],
        "similarity": None if pd.isna(last["similarity"]) else float(last["similarity"]),
        "words_added": None if pd.isna(last["words_added"]) else int(last["words_added"]),
        "words_removed": None if pd.isna(last["words_removed"]) else int(last["words_removed"]),
        "holds_in_a_row": holds,
        "last_move": records(moves.tail(1)[["doc_id", "release_date", "change_bp"]])[0] if len(moves) else None,
        "net_12m_bp": int(since["change_bp"].fillna(0).sum()),
        "median_similarity": float(df["similarity"].median()),
    }
    return {"method": method, "decisions": records(df), "current": current}


@app.get("/api/validity")
def validity(con=Depends(get_con)):
    return records(db.query(con, "SELECT * FROM validity ORDER BY macro_f1 DESC"))


@app.get("/api/findings")
def findings_(con=Depends(get_con)):
    """The four hypotheses with their verdicts and one number each: the Home page's research summary."""
    from . import findings

    return findings.summary(con)


@app.get("/api/forecast")
def forecast_(con=Depends(get_con)):
    """Exploratory: does the tone of the minutes, speeches and statements add to what the market prices about the
    next decision? In-sample fit, expanding-window forecasts from 2017 and each forecast made."""
    row = con.execute("SELECT value FROM meta WHERE key = 'forecast'").fetchone()
    return json.loads(row[0]) if row else {}


@app.get("/api/forward")
def forward_test(con=Depends(get_con)):
    """Since the freeze: the frozen rules on new data (written by `fomc forward` every evening)."""
    row = con.execute("SELECT value FROM meta WHERE key = 'forward'").fetchone()
    return json.loads(row[0]) if row else {}


@app.get("/api/reliability")
def reliability(con=Depends(get_con)):
    """How far to trust the readings: Claude against each baseline (paired bootstrap, McNemar), test-retest
    stability, the memorization audit (masked dating and masked rescoring), and how closely the RoBERTa readers'
    document scores track Claude's."""
    rows = con.execute("SELECT key, value FROM meta WHERE key IN ('validity_tests', 'audit', 'readers')").fetchall()
    meta = dict(rows)
    audit = json.loads(meta["audit"]) if "audit" in meta else {}
    return {
        "tests": json.loads(meta["validity_tests"]) if "validity_tests" in meta else [],
        "readers": {  # the document scores stay in the store, for the Story
            name: {k: v for k, v in reader.items() if k != "scores"}
            for name, reader in (json.loads(meta["readers"]) if "readers" in meta else {}).items()
        },
        "stability": audit.get("stability"),
        "identify": audit.get("identify"),
        "invariance": audit.get("invariance"),
        "drift": audit.get("drift"),
    }


# --------------------------------------------------------------- duration
def _duration_primary(con):
    rows = db.query(con, "SELECT run_id, method, doc_types, entry, hold FROM backtests WHERE is_primary=1 LIMIT 1")
    if rows.empty:
        return None
    row = records(rows)[0]
    if (
        not row["method"]
        or not row["doc_types"]
        or row["entry"] not in ("etf_entry", "etf_entry_next")
        or not row["hold"]
    ):
        return None
    return row


@app.get("/api/duration")
def duration_info(con=Depends(get_con)):
    from . import findings

    cfg = settings()["backtest"]
    try:
        assumed = duration.assumptions(cfg)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Duration assumptions are unavailable.") from exc
    primary = _duration_primary(con)
    choices = []
    if primary:
        choices = records(
            db.query(
                con,
                "SELECT d.doc_id, d.doc_type, d.release_date, d.title, d.speaker "
                "FROM documents d JOIN scores s ON s.doc_id=d.doc_id AND s.method=? "
                "WHERE d.note IS NULL ORDER BY d.release_date DESC,d.doc_id LIMIT 80",
                (primary["method"],),
            )
        )
    return {
        "defaults": {
            **duration.ScenarioIn().model_dump(),
            "duration_budget": cfg["duration_budget_years"],
            "cost_bp_per_side": cfg["cost_bp_per_side"],
        },
        "assumptions": assumed,
        "market_as_of": con.execute("SELECT MAX(date) FROM etf_prices").fetchone()[0],
        "research": next((f for f in findings.summary(con) if f["key"] == "h3"), None),
        "primary": primary,
        "documents": choices,
    }


@app.get("/api/duration/context")
def duration_context(doc_id: str | None = Query(None, max_length=150), con=Depends(get_con)):
    primary = _duration_primary(con)
    if primary is None:
        return {"context": None, "reason": "No frozen primary strategy is stored."}
    frame = db.query(
        con,
        "SELECT d.doc_id,d.doc_type,d.release_date,d.release_time_et,d.title,d.speaker,d.url,"
        "e.avail_ts,e.etf_entry,e.etf_entry_next,s.score,"
        "coalesce(json_extract(s.details,'$.policy_relevance'),'') AS relevance "
        "FROM documents d JOIN events e ON e.doc_id=d.doc_id "
        "JOIN scores s ON s.doc_id=d.doc_id AND s.method=? WHERE d.note IS NULL",
        (primary["method"],),
    )
    context = duration.document_context(frame, doc_id, settings()["backtest"], primary)
    if doc_id is not None and context is None:
        raise HTTPException(404, "No aligned reading from the frozen reader exists for this document.")
    return jsonable({"context": context, "reason": None if context else "No aligned readings are stored."})


@app.get("/api/sources")
def data_sources(con=Depends(get_con)):
    return {"sources": provenance.sources(con), "research_freeze": settings()["forward"]["freeze"]}


@app.post("/api/duration/scenario")
def duration_scenario(body: duration.ScenarioIn):
    """Pure calculation: no scoring, storage writes, quotes or research re-estimation."""
    try:
        return duration.scenario(body, settings()["backtest"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Duration assumptions are unavailable.") from exc


@app.get("/api/backtests")
def backtests(con=Depends(get_con)):
    return records(db.query(con, "SELECT * FROM backtests ORDER BY is_primary DESC, sharpe DESC"))


def _tilt_scale() -> float:
    """Overlay units per year of portfolio duration (same formula as evaluate.backtest.tilt_scale)."""
    cfg = settings()["backtest"]
    return cfg["duration_budget_years"] / (cfg["durations"][cfg["long_etf"]] - cfg["durations"][cfg["short_etf"]])


@app.get("/api/backtests/curve")
def backtest_curve(run_id: str, benchmark: str = "", con=Depends(get_con)):
    """Cumulative overlay return; with `benchmark` (AGG or IEI), also the benchmark and the tilted portfolio."""
    from . import store

    ret = store.load_curve(con, run_id)
    if ret.empty:
        raise HTTPException(404, "unknown run")
    ret = ret.astype(float)
    out = pd.DataFrame({"cum": ret.cumsum()})
    if benchmark:
        if benchmark not in settings()["backtest"]["portfolio_benchmarks"]:
            raise HTTPException(400, "unknown benchmark")
        px = db.query(
            con, f"SELECT date, {benchmark} AS px FROM etf_prices WHERE date >= ? ORDER BY date", (ret.index[0],)
        ).set_index("date")["px"]
        b = px.pct_change().reindex(ret.index).fillna(0.0)
        out["bench"] = (1 + b).cumprod() - 1
        out["port"] = (1 + b + _tilt_scale() * ret).cumprod() - 1
    return [{"date": d, **{k: round(float(v), 6) for k, v in row.items()}} for d, row in out.iterrows()]


@app.get("/api/pipeline")
def pipeline(con=Depends(get_con)):
    stages = db.query(
        con,
        "SELECT p.stage, p.status, p.started_at, p.finished_at, p.detail FROM pipeline_runs p "
        "JOIN (SELECT stage, max(id) AS id FROM pipeline_runs GROUP BY stage) m ON m.id = p.id",
    )
    stages["detail"] = stages["detail"].map(lambda d: json.loads(d) if d else {})
    batches = db.query(con, "SELECT * FROM llm_batches ORDER BY created_at DESC")
    return {"stages": records(stages), "batches": records(batches), "research_freeze": settings()["forward"]["freeze"]}


@app.get("/api/system")
def system(con=Depends(get_con)):
    """Storage, cache and throughput figures for the System section's Data page."""
    from .config import LLM_DIR, RAW

    def size(path: Path) -> tuple[int, int]:
        files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
        return len(files), sum(p.stat().st_size for p in files)

    db_bytes = db.store_bytes()
    tables = [
        "documents",
        "documents_fts",
        "events",
        "scores",
        "yields",
        "etf_prices",
        "llm_records",
        "llm_batches",
        "decisions",
        "policy_rates",
        "committee",
        "validity",
        "event_study",
        "event_curves",
        "backtests",
        "backtest_curves",
        "label_items",
        "labels",
        "label_predictions",
        "pipeline_runs",
    ]
    rows = [{"table": t, "rows": con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]} for t in tables]
    raw_n, raw_b = size(RAW)
    raw_live = raw_n > 0
    if not raw_live:  # the hosted image ships the store, not the download cache: report the last run's count
        facts = con.execute("SELECT value FROM meta WHERE key = 'facts'").fetchone()
        raw_n, raw_b = (json.loads(facts[0]).get("raw_files", 0) if facts else 0), None
    llm_n, llm_b = size(LLM_DIR)
    allruns = db.query(con, "SELECT id, stage, status, started_at, finished_at FROM pipeline_runs ORDER BY id")
    allruns["seconds"] = (
        pd.to_datetime(allruns["finished_at"]) - pd.to_datetime(allruns["started_at"])
    ).dt.total_seconds()
    last = allruns.groupby("stage").tail(1).set_index("stage")
    ok = allruns[allruns["status"] == "ok"].groupby("stage").tail(1).set_index("stage")
    runs = pd.DataFrame(
        {
            "stage": last.index,
            "status": last["status"].to_numpy(),
            "finished_at": last["finished_at"].to_numpy(),
            "seconds": [ok["seconds"].get(st) for st in last.index],
            "last_ok_at": [ok["finished_at"].get(st) for st in last.index],
        }
    )
    tokens = con.execute(
        "SELECT coalesce(sum(input_tokens),0), coalesce(sum(cache_read_tokens),0), "
        "coalesce(sum(output_tokens),0), count(*), coalesce(sum(batch_id IS NOT NULL),0) "
        "FROM llm_records"
    ).fetchone()
    words = con.execute("SELECT coalesce(sum(n_words), 0) FROM documents WHERE note IS NULL").fetchone()[0]
    source = con.execute("SELECT value FROM meta WHERE key = 'yield_source'").fetchone()
    return {
        "yield_source": source[0] if source else None,
        "yields_through": con.execute("SELECT max(date) FROM yields WHERE t2y IS NOT NULL").fetchone()[0],
        "db": {"path": str(db.DB_PATH.name), "bytes": db_bytes, "schema_version": db.SCHEMA_VERSION},
        "tables": rows,
        "raw_cache": {"files": raw_n, "bytes": raw_b, "live": raw_live},
        "llm_store": {
            "files": llm_n,
            "bytes": llm_b,
            "input_tokens": tokens[0],
            "cache_read_tokens": tokens[1],
            "output_tokens": tokens[2],
            "records": tokens[3],
            "batched": tokens[4],
        },
        "words": words,
        "runs": records(runs),
    }


# ------------------------------------------------------------- team labels
class LabelIn(BaseModel):
    item_id: int
    annotator: str = Field(..., min_length=1, max_length=40)
    label: int = Field(..., ge=-1, le=1)


class AnnotatorIn(BaseModel):
    annotator: str = Field(..., min_length=1, max_length=40)


def _labels_writable() -> None:
    if PUBLIC:
        raise HTTPException(403, "Labeling is available in the local workspace (make serve); this demo is read-only.")


@app.get("/api/labels/summary")
def labels_summary(con=Depends(get_con)):
    from . import labels

    return {**labels.summary(con), "writable": not PUBLIC}


@app.get("/api/labels/next")
def labels_next(annotator: str = Query(..., min_length=1, max_length=40), con=Depends(get_con)):
    from . import labels

    name = annotator.strip()
    return {"item": labels.next_item(con, name), "progress": labels.progress(con, name)}


@app.post("/api/labels")
def labels_post(body: LabelIn, con=Depends(get_con)):
    _labels_writable()
    from . import labels

    try:
        labels.record(con, body.item_id, body.annotator.strip(), body.label)
    except KeyError as exc:
        raise HTTPException(404, "unknown item") from exc
    name = body.annotator.strip()
    return {"item": labels.next_item(con, name), "progress": labels.progress(con, name)}


@app.post("/api/labels/undo")
def labels_undo(body: AnnotatorIn, con=Depends(get_con)):
    _labels_writable()
    from . import labels

    name = body.annotator.strip()
    item_id = labels.undo(con, name)
    item = None
    if item_id is not None:
        df = db.query(
            con,
            "SELECT i.item_id, i.doc_id, i.sentence, i.context_before, i.context_after, d.doc_type, "
            "d.release_date, d.title, d.speaker FROM label_items i JOIN documents d ON d.doc_id = i.doc_id "
            "WHERE i.item_id = ?",
            (item_id,),
        )
        item = records(df)[0] if len(df) else None
    return {"item": item, "progress": labels.progress(con, name)}


# ---------------------------------------------------------------- settings
class SettingsIn(BaseModel):
    api_key: str | None = None
    model: str | None = None
    effort: str | None = Field(None, pattern="^(low|medium|high|xhigh|max)$")
    clear_key: bool = False


def _status() -> dict:
    st = provider.status()
    st["read_only"] = PUBLIC
    st["score_enabled"] = bool(st["key_configured"] and (not PUBLIC or SCORE_TOKEN))
    st["score_token_required"] = bool(PUBLIC and SCORE_TOKEN)
    if PUBLIC:
        st["key_hint"] = None  # never describe the server's key on a hosted deployment
    return st


def _writable() -> None:
    if PUBLIC:
        raise HTTPException(403, "This is a read-only deployment; settings are managed with environment variables.")


@app.get("/api/settings")
def get_settings():
    return _status()


@app.post("/api/settings")
def post_settings(body: SettingsIn):
    _writable()
    if body.clear_key:
        provider.clear_key()
    if body.api_key:
        try:
            provider.save_key(body.api_key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if body.model or body.effort:
        if body.model and body.model not in settings()["llm"]["prices_per_mtok"]:
            raise HTTPException(400, "unknown model")
        provider.save_local(body.model, body.effort)
    return _status()


@app.post("/api/settings/check")
def check_settings():
    _writable()
    return provider.check()


# ------------------------------------------------------------- live score
class ScoreIn(BaseModel):
    text: str = Field(..., min_length=50, max_length=60000)
    doc_type: str = Field("speech", pattern="^(statement|minutes|presser|speech)$")
    model: str | None = None


@app.post("/api/score")
def live_score(body: ScoreIn, con=Depends(get_con), x_score_token: str = Header(default="")):
    from .llm import rubric
    from .llm.scorer import Scorer, live_job

    if PUBLIC and not (SCORE_TOKEN and secrets.compare_digest(x_score_token, SCORE_TOKEN)):
        raise HTTPException(
            403,
            "Live scoring is off on this public deployment. Run the project locally with "
            "your own key, or enter the access token from the owner.",
        )
    if not provider.status()["key_configured"]:
        raise HTTPException(400, "No API key configured. Add one on the Settings page.")
    if body.model and body.model not in settings()["llm"]["prices_per_mtok"]:
        raise HTTPException(400, f"Unknown model {body.model!r}; choose one of the models in Settings.")
    sc = Scorer(model=body.model)
    rec = sc.call(live_job(body.text, body.doc_type))
    if rec["status"] != "ok":
        raise HTTPException(502, f"model returned {rec['status']}: {rec.get('error')}")
    parsed = rec["parsed"]
    hist = db.query(
        con,
        f"SELECT s.score FROM scores s JOIN documents d ON d.doc_id = s.doc_id WHERE s.method = ? AND d.doc_type = ? "
        f"AND {RELEVANT}",
        (f"llm:{sc.model}:{rubric.RUBRIC_VERSION}", body.doc_type),
    )["score"].dropna()
    bt = settings()["backtest"]
    tilt = None  # a document with little to say about monetary policy gets no signal, as in the backtest
    if len(hist) >= bt["zscore_min_events"] and hist.std() > 0 and parsed.get("policy_relevance") != "low":
        z = (parsed["stance_score"] - hist.mean()) / hist.std()
        theta = float(-np.clip(z, -2, 2) / 2)
        tilt = {"z": z, "theta": theta, "duration_years": theta * bt["duration_budget_years"], "history_n": len(hist)}
    price = settings()["llm"]["prices_per_mtok"].get(sc.model, {"input": 0, "output": 0})
    u = rec["usage"]
    cost = ((u.get("input_tokens") or 0) * price["input"] + (u.get("output_tokens") or 0) * price["output"]) / 1e6
    return {
        "model": rec["model_served"],
        "parsed": parsed,
        "checks": rec.get("checks"),
        "usage": u,
        "cost_usd": cost,
        "tilt": tilt,
        "tilt_min_events": bt["zscore_min_events"],
    }
