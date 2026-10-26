"""The story: the whole project as a slide deck, built from the store every time it is asked for.

One source for three uses: the Story page in the dashboard (present it live), `fomc slides` (a
PowerPoint with the same slides, editable titles and speaker notes), and the outline teammates can
paste into any template. Content slides carry a causal-sentence title, at most one number to remember,
a one-line takeaway, a source line, speaker notes and a link into the app. Section dividers split the
deck into the parts of the work; the opening states the assignment and the answers first.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd

from . import db, findings
from .config import settings

GROUP_NAMES = {
    "statement": "statements",
    "minutes": "minutes",
    "presser": "press conferences",
    "speech": "Board speeches",
    "speech_chair": "the Chair’s speeches",
    "speech_other": "other members’ speeches",
}
TYPE_LABELS = {"statement": "statements", "minutes": "minutes", "presser": "press conferences", "speech": "speeches"}
TENOR_NAMES = {"d3m": "3-month bill", "d2y": "2-year", "d5y": "5-year", "d10y": "10-year", "d30y": "30-year"}
MINUS = re.compile(r"(?<![\w.])-(?=\d)")  # a hyphen before a number becomes a true minus sign on the slide
SECTIONS = [
    ("01", "Data and timing", "What we read, and the minute each document became public"),
    ("02", "Reading the Fed", "Claude against three simpler readers and a trained transformer, with evidence"),
    ("03", "What the market does", "Release-day moves, a duration trade, a memorization check and the next decision"),
    ("04", "How it is built", "Architecture, engineering and the product"),
]
MAIN_SECTIONS = [
    ("Question and data", "The task, course connections, corpus and release clocks"),
    ("Readers and validation", "Claude, local fine-tuning, expert labels and contamination"),
    ("Index, yields and duration", "Tone history, release-window tests and the duration trade"),
    ("Forward checks and system", "Prospective evaluation, implementation and the dashboard"),
    ("Conclusions and limits", "Brief coverage, practical findings and remaining uncertainty"),
]


def decision_mix(counts: dict) -> str:
    """'21 hikes, 11 cuts, 111 holds' from the decisions table's action codes (1, -1, 0)."""
    return ", ".join(f"{counts.get(k, 0)} {name}" for k, name in ((1, "hikes"), (-1, "cuts"), (0, "holds")))


def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def _label(method: str) -> str:
    """The same names the dashboard uses (methodLabel in app.js)."""
    if method.startswith("llm:"):
        return "Claude " + method.split(":")[1].replace("claude-", "").replace("-", " ").title().replace(" 5 5", " 5.5")
    if method.startswith("llmshift:"):
        return "Claude vs previous statement"
    return {
        "dictionary": "Dictionary",
        "supervised": "TF-IDF classifier",
        "embedding": "Sentence embeddings",
        "roberta_tuned": "Fine-tuned RoBERTa",
        "fomc_roberta": "FOMC-RoBERTa",
    }.get(method, method)


def _ordinal(p: float) -> str:
    n = round(p)
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _meta(con, key: str) -> dict:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else {}


def _cost_range(con) -> tuple[float, float]:
    """Batch cost to score the corpus once, cheapest and dearest model (offline token approximation)."""
    cfg = settings()["llm"]
    words = db.query(con, "SELECT count(*) AS n, coalesce(sum(n_words), 0) AS w FROM documents WHERE note IS NULL")
    n, w = int(words["n"].iloc[0]), float(words["w"].iloc[0])
    tokens_in, tokens_out = n * 1800 + 1.35 * w, n * cfg["assumed_output_tokens"]
    costs = [
        cfg["batch_discount"] * (tokens_in * p["input"] + tokens_out * p["output"]) / 1e6
        for p in cfg["prices_per_mtok"].values()
    ]
    return min(costs), max(costs)


# ------------------------------------------------------------------------ context
def _context(con) -> dict:
    """Everything the slides need, read once."""
    from . import api

    c = {"proj": settings()["project"], "con": con}
    c["pulse"] = api.pulse(con)
    c["method"] = c["pulse"]["method"] or ""
    c["readings"] = {r["doc_type"]: r for r in c["pulse"]["readings"]}
    c["fed"] = api.fed_now(con)
    c["tracker"] = api.tracker(con)
    c["es"] = pd.DataFrame(api.event_study("", "", "", con))
    c["bt"] = pd.DataFrame(api.backtests(con))
    c["val"] = db.query(con, "SELECT method, macro_f1, cohen_kappa, accuracy, n FROM validity ORDER BY macro_f1 DESC")
    c["docs"] = db.query(
        con, "SELECT doc_type, count(*) AS n, sum(n_words) AS w FROM documents WHERE note IS NULL GROUP BY doc_type"
    ).set_index("doc_type")
    c["total"] = int(c["docs"]["n"].sum()) if len(c["docs"]) else 0
    c["words"] = float(c["docs"]["w"].sum()) if len(c["docs"]) else 0.0
    recs = db.query(con, "SELECT mode, run_tag, status, evidence_share, cost_usd FROM llm_records")
    level = recs[(recs["mode"] == "level") & (recs["status"] == "ok") & (recs["run_tag"].fillna("") == "")]
    c["llm"] = {
        "records": len(recs),
        "level": len(level),
        "failed": int((recs["status"] != "ok").sum()),
        "share": float(level["evidence_share"].dropna().mean()) if len(level) else None,
        "cost": float(recs["cost_usd"].fillna(0).sum()),
        "batches": con.execute("SELECT count(DISTINCT batch_id) FROM llm_records").fetchone()[
            0
        ],  # batches that produced records
    }
    methods = c["es"]["method"].unique() if len(c["es"]) else []
    c["llm_method"] = next((m for m in methods if str(m).startswith("llm:")), None)
    ysrc = con.execute("SELECT value FROM meta WHERE key = 'yield_source'").fetchone()
    c["fred"] = not ysrc or ysrc[0].startswith("FRED")  # else the Treasury par curve, the series FRED republishes
    c["audit"] = _meta(con, "audit")
    c["forecast"] = _meta(con, "forecast")
    tests = con.execute("SELECT value FROM meta WHERE key = 'validity_tests'").fetchone()
    tests = [t for t in (json.loads(tests[0]) if tests else []) if t["method"] in findings.BASELINES]
    c["lead"] = min(tests, key=lambda t: t["f1_diff"]) if tests else None  # Claude against its closest baseline
    c["decision_counts"] = dict(
        con.execute("SELECT action, count(*) FROM decisions WHERE action IS NOT NULL GROUP BY action").fetchall()
    )
    c["facts"] = _meta(con, "facts")
    c["items"] = con.execute("SELECT count(*) FROM label_items").fetchone()[0]
    c["human_labels"] = con.execute("SELECT count(*) FROM labels").fetchone()[0]
    c["tables"] = con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'documents_fts%'"
    ).fetchone()[0]
    c["endpoints"] = sum(1 for r in api.app.routes if getattr(r, "path", "").startswith("/api/"))
    c["post_cutoff_docs"] = con.execute(
        "SELECT count(*) FROM documents WHERE note IS NULL AND release_date >= ?",
        (settings()["splits"]["post_cutoff"][0],),
    ).fetchone()[0]

    es = c["es"]
    main = es[(es["sample"] == "all") & (es["control"] == "none")] if len(es) else es
    c["main"] = main
    c["tests"] = main[main["q_bh"].notna()] if len(main) else main
    c["survivors"] = c["tests"][c["tests"]["q_bh"] < 0.10] if len(c["tests"]) else c["tests"]
    d2y = main[(main["outcome"] == "d2y") & main["doc_type"].isin(list(TYPE_LABELS))] if len(main) else main
    c["best"] = d2y.loc[d2y["t"].abs().idxmax()] if len(d2y) else None
    bt = c["bt"]
    c["primary"] = bt[bt["is_primary"] == 1].iloc[0] if len(bt) and (bt["is_primary"] == 1).any() else None
    val = c["val"]
    llm_val = val[val["method"].str.startswith("llm:")] if len(val) else val
    base_val = val[val["method"].isin(findings.BASELINES)] if len(val) else val  # FOMC-RoBERTa is a reference
    c["f1_llm"] = float(llm_val["macro_f1"].iloc[0]) if len(llm_val) else None
    c["kappa_llm"] = float(llm_val["cohen_kappa"].iloc[0]) if len(llm_val) else None
    c["f1_base"] = float(base_val["macro_f1"].max()) if len(base_val) else None
    c["kappa_base"] = float(base_val["cohen_kappa"].max()) if len(base_val) else None
    c["verdicts"] = _verdicts(c)
    return c


def _verdicts(c) -> dict:
    """Each hypothesis judged once (findings.py), so the titles, cards and takeaways can never disagree with the
    numbers or with the Home page."""
    return findings.verdicts(c["con"])


def _same(es: pd.DataFrame, row, **kw):
    sel = es[
        (es["doc_type"] == row["doc_type"]) & (es["method"] == row["method"]) & (es["regressor"] == row["regressor"])
    ]
    for k, v in kw.items():
        sel = sel[sel[k] == v]
    return sel.iloc[0] if len(sel) else None


# -------------------------------------------------------------------------- slides
def _cover(c):
    return {
        "id": "cover",
        "layout": "cover",
        "kicker": f"{c['proj']['group']} · {c['proj']['course'].split(',')[0]} · Fall 2026",
        "title": "FOMC Tone Lab",
        "subtitle": "Measuring Fed Communication and Testing Duration Signals",
        "team": c["proj"]["team"],
        "notes": "We are Group 2. Our topic is the central bank communication index: read everything the Fed publishes, "
        "score its tone with Claude, see whether Treasuries react, and ask whether a duration trade can use it. "
        "Everything on these slides is computed live from our system.",
        "link": "#/overview",
    }


def _extreme_quote(con, hawkish: bool) -> dict | None:
    """The latest statement at Claude's most hawkish (or dovish) reading, with one short quote of its evidence."""
    row = con.execute(
        "SELECT d.release_date, json_extract(r.parsed, '$.stance_score') AS s, r.parsed FROM llm_records r "
        "JOIN documents d ON d.doc_id = r.key WHERE r.mode = 'level' AND coalesce(r.run_tag, '') = '' "
        "AND r.status = 'ok' AND d.doc_type = 'statement' "
        f"ORDER BY s {'DESC' if hawkish else 'ASC'}, d.release_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    order = ("forward_guidance", "policy_action", "risk_balance", "inflation_assessment")
    short = [
        e for e in json.loads(row[2]).get("evidence", []) if e.get("dimension") in order and len(e["quote"]) <= 110
    ]
    if not short:
        return None
    quote = min(short, key=lambda e: order.index(e["dimension"]))["quote"].strip().rstrip(".")
    return {
        "side": "hawk" if hawkish else "dove",
        "label": "Hawkish" if hawkish else "Dovish",
        "gloss": "tighter policy ahead: higher rates to cool inflation"
        if hawkish
        else "easier policy ahead: lower rates to support jobs and growth",
        "text": ("…" if quote[:1].islower() else "") + quote,
        "when": f"{date.fromisoformat(row[0]):%-d %B %Y} statement",
        "date": f"{date.fromisoformat(row[0]):%-d %b %Y}",
        "score": row[1],
    }


def _primer(c):
    bt = settings()["backtest"]
    dur, budget = bt["durations"], bt["duration_budget_years"]
    quotes = [q for q in (_extreme_quote(c["con"], True), _extreme_quote(c["con"], False)) if q]
    steps = [
        {
            "title": "The Fed speaks",
            "body": "Eight decisions a year: a statement at 2:00 p.m., the Chair’s press conference at 2:30, minutes "
            "three weeks later, and speeches in between.",
            "foot": f"{c['total']:,} documents since 2009",
        },
        {"title": "Its tone: hawkish or dovish", "quotes": quotes},
        {
            "title": "Yields move",
            "body": "Hawkish news raises the expected path of the policy rate, so yields rise, most at two to five years; "
            "dovish news pulls them down.",
            "foot": "Bond prices move the other way",
        },
        {
            "title": "Duration sets the gain or loss",
            "formula": "ΔP / P ≈ −D × Δy",
            "body": f"If yields rise 10 bp, IEF (D ≈ {dur['IEF']:g}) loses about {dur['IEF'] / 10:.1f}% and SHY "
            f"(D ≈ {dur['SHY']:g}) about {dur['SHY'] / 10:.1f}%.",
            "foot": f"Hawkish: shorten. Dovish: lengthen. Within ±{budget:g} year.",
        },
    ]
    examples = " and ".join(f"{q['date']} ({q['score']:+.2f})".replace("-", "−") for q in quotes)
    return {
        "id": "primer",
        "layout": "wide",
        "kicker": "Topic 4 in one picture",
        "title": "The Fed moves Treasuries with words",
        "subtitle": "So its tone might tell a bond portfolio how much duration to hold",
        "desk": "Can Claude read the Fed’s tone well and early enough to lean duration before the market prices it?",
        "desk_label": "The question",
        "source": (f"Quotes: Claude’s evidence from the statements of {examples}; " if quotes else "")
        + "SHY and IEF durations as in the backtest.",
        "notes": "Before the results, the idea. The Fed sets short-term interest rates, and it signals where they are going "
        "through what it says: statements, minutes, press conferences and speeches. When it sounds hawkish, ready to raise "
        "rates to cool inflation, yields rise and bond prices fall; when it sounds dovish, they move the other way. How "
        "much a bond portfolio gains or loses depends on its duration: seven years of duration loses about seven percent "
        "if yields rise one point. So the topic asks: can we read the tone of the Fed’s words, turn it into an index, and "
        "use it to decide how much duration to hold?",
        "link": "#/tracker",
        "visual": {"kind": "primer", "steps": steps},
    }


def _brief(c):
    share = c["llm"]["share"]
    rows = [
        [
            "A hawkish-dovish index from statements, minutes, press-conference transcripts and governor speeches",
            f"{c['total']:,} documents from the Fed’s website since 2009, each stamped with its release minute",
        ],
        [
            "Claude scores each document on a defined rubric with evidence spans",
            "Rubric v1: six policy dimensions and a stance from −1 to +1"
            + (f"; mean document evidence-match share {share:.2%}" if share else "; every quote located in the source"),
        ],
        [
            "Compared with simpler baselines: dictionary methods and sentence-level embeddings",
            "Dictionary, TF-IDF classifier and MiniLM sentence embeddings, judged on the same human labels",
        ],
        [
            "Tested against subsequent Treasury yield changes from FRED across the curve",
            "FRED yields, 3-month to 30-year, and the 2s10s slope over each release window, with placebo, controls and FDR"
            if c["fred"]
            else "3-month to 30-year yields and the 2s10s slope over each release window; FRED first, the Treasury par "
            "curve it republishes as fallback (used this run)",
        ],
        [
            "A duration tilt in a Treasury or aggregate-bond portfolio, respecting that statements are priced within minutes",
            "IEF against SHY, applied to AGG and IEI; entry the day after release; minutes, speeches and statement-to-statement shifts",
        ],
    ]
    return {
        "id": "brief",
        "layout": "wide",
        "kicker": "The assignment · Topic 4",
        "title": "What the brief asks, and what we built",
        "subtitle": "Topic 4: a central bank communication index and duration positioning",
        "desk": "The brief’s key insight shapes every test: the market reprices a statement within minutes, so any "
        "tradable edge has to sit in slower documents or in the change of tone.",
        "desk_label": "Why it matters",
        "source": "IEOR 4723 final project brief, topic 4; the right-hand column is what this project delivers.",
        "notes": "Our topic is number four: build a hawkish-dovish index from everything the Fed publishes, score it with "
        "Claude against a defined rubric with evidence, compare it with simpler baselines, test it on Treasury yields "
        "across the curve, and use it to tilt duration in a bond portfolio. The left column is what the brief asks for; "
        "the right column is what we built for each line.",
        "link": "#/overview",
        "visual": {"kind": "brief", "rows": rows},
    }


def _agenda(c):
    return {
        "id": "agenda",
        "layout": "wide",
        "kicker": "Roadmap",
        "title": "Contents",
        "subtitle": "The investment question, the measurement test and the portfolio test are separate steps",
        "source": "Page ranges follow this integrated presentation and update when data-dependent slides are omitted.",
        "notes": "First define the investment question and the information available at each release. Then explain "
        "the readers, including the model fine-tuned locally, before judging their accuracy and recognition risk. "
        "Only then move to Treasury responses and the delayed duration trade. Forward evaluation and implementation "
        "follow the research results, and the close separates delivered functionality from evidence of profitability.",
        "link": "#/pipeline",
        "visual": {"kind": "table", "columns": ["Section", "What it answers", "Slides"], "rows": []},
    }


def _course_links(c):
    variants = len(c["bt"]) if len(c["bt"]) else "all"
    return {
        "id": "course-links",
        "layout": "wide",
        "kicker": "From the course",
        "title": "What we learned in the course, and how we used it",
        "subtitle": "Six lessons from the lectures, each put to work in this project",
        "source": "Lectures, Sessions 1 to 4, and the Topic 4 brief; page references in docs/COURSE_ALIGNMENT.md.",
        "notes": "Six things from the lectures shaped how we built this. From Session One: prompting a general model "
        "has a ceiling, and training on labeled data can go past it, so we fine-tuned RoBERTa on the expert labels "
        "and report that it beats Claude. From Session Two: treat the prompt as a specification you version and "
        "check, and test whether a model is simply remembering history; hence the JSON rubric, the quote checks, "
        "the masked dates and the re-scoring. From Session Three: use only information that was public at the "
        "time, and count every variant you try; hence the release clocks, the next-close entry, and every strategy "
        "reported with costs and a placebo, including the one that failed. From Session Four: ground answers in "
        "sources; every score links back to the Fed's own words, and the archive is searchable by full text.",
        "link": "#/system",
        "visual": {
            "kind": "table",
            "columns": ["What we learned", "How we applied it"],
            "rows": [
                [
                    "A prompt has a ceiling; training on labeled data can go further",
                    "Fine-tuned RoBERTa on the expert labels as a reference reader, and report that it beats Claude",
                ],
                [
                    "Treat the prompt as a specification: version it and check the output",
                    "One rubric enforced as a JSON schema; every quote is checked against the Fed's text",
                ],
                [
                    "A model may remember history; test for it before trusting a score",
                    "Masked dates and names, asked Claude to date statements, re-scored to check stability",
                ],
                [
                    "Use only what was public at the time",
                    "Timestamped every release; trades enter at the first close after publication",
                ],
                [
                    "Count every variant you try, and charge for costs",
                    f"Reported {variants} strategy variants with costs and placebos, including the negative result",
                ],
                [
                    "Ground answers in sources",
                    "Every score links to the Fed's own words; the full archive is searchable",
                ],
            ],
        },
    }


def _local_training(c):
    reader = _meta(c["con"], "readers").get("roberta_tuned", {})
    if not reader.get("chosen") or not reader.get("search"):
        return None
    chosen = reader["chosen"]
    cfg = chosen["config"]
    seeds = len(reader.get("seed_macro_f1", []))
    tested = c["val"][c["val"]["method"] == "roberta_tuned"]
    test_n = int(tested["n"].iloc[0]) if len(tested) else 496
    lr = f"{cfg['lr']:.0e}".replace("e-0", "e-")
    return {
        "id": "local-training",
        "layout": "wide",
        "kicker": "The model we trained locally",
        "title": "How we fine-tuned RoBERTa locally",
        "subtitle": "A supervised reference added after the original study, using public expert labels",
        "source": "finetune.py; stored readers.roberta_tuned; data/baselines/roberta-tuned.json (device: MPS, split hashes, revisions, runs).",
        "notes": "The model is a pretrained RoBERTa encoder with a three-class classification head. We update all "
        "its parameters locally on an Apple GPU through PyTorch MPS. The saved record identifies the backbone "
        "revision, train/test sentence hashes, device, software versions, every search run and the final seeds. "
        "The 1,984 training sentences and the 496-sentence held-out test are the same split used by the supervised "
        "baselines. Five-fold stratified validation selects architecture, learning rate and stopping epoch without "
        "consulting test performance. Training uses class-balanced cross-entropy, AdamW, 10% warmup, linear decay "
        "and gradient clipping. The final chosen configuration is fit on all training sentences with five seeds; "
        "their class probabilities are averaged before the fixed ensemble is evaluated. Document tone is the mean "
        "of P(hawkish) minus P(dovish) across sentences. This reference was added after the original results and "
        "does not replace the frozen Claude H1 comparison, event study or duration strategy. The next slide shows "
        "the complete parameter search; the following slides compare held-out performance.",
        "link": "#/validity",
        "visual": {
            "kind": "steps",
            "steps": [
                [
                    "Keep the split fixed",
                    f"1,984 public expert training sentences; {test_n:,} held out. Three classes: dovish, neutral and hawkish.",
                ],
                [
                    "Select on validation folds",
                    f"{len(reader['search'])} settings across 5 stratified folds. Mean validation macro-F1 selects the setting and epoch.",
                ],
                [
                    "Fit the chosen model locally",
                    f"Full-parameter RoBERTa fine-tuning on Apple MPS; {seeds} seeds. Chosen learning rate {lr}, stopping at epoch {chosen['epoch']}.",
                ],
                [
                    "Evaluate the fixed ensemble",
                    "Average the seeds' class probabilities. Test once; then average P(hawkish) minus P(dovish) over each document's sentences.",
                ],
            ],
        },
    }


def _beyond(c):
    return {
        "id": "beyond",
        "layout": "wide",
        "kicker": "Beyond topic 4",
        "title": "What we added beyond the brief",
        "subtitle": "Measurement checks, a forward test, and a system that keeps the evidence auditable",
        "source": "docs/ASSIGNMENT.md; finetune.py, evaluate/forward.py, audit.py, members.py, api.py and cli.py.",
        "notes": "These additions extend the brief without changing the frozen H1 to H4 results. The trained "
        "transformer and forecast are exploratory references. The forward test uses new releases under fixed rules.",
        "link": "#/system",
        "visual": {
            "kind": "tiles",
            "tiles": [
                ["RoBERTa", "Fine-tuned on the same labels; a reference added after the results, outside H1"],
                ["Forward test", "Frozen coefficients and trading rules applied only to releases after the freeze"],
                ["Monthly re-reads", "The same anchor documents reveal changes in the model or scoring pipeline"],
                ["Member timelines", "Fed biographies, speech-tone turning points, titles and dissent histories"],
                ["Atom feed", "Subscribe to new releases, their tone and links to the Fed's source documents"],
                ["Freeze guards", "Research and baseline results stay fixed while new documents receive scores"],
                ["Refresh and caps", "Automatic collection and refresh, with spending limits and freshness checks"],
                ["Shared store", "The unified story and read-only dashboard read the same versioned store"],
            ],
        },
    }


def _answers(c):
    cards = []
    if c["f1_llm"] is not None and c["f1_base"] is not None:
        cards.append(
            [
                "H1 · Measurement",
                "Claude matches public expert labels better than the baselines",
                c["verdicts"]["h1"] + " on public expert labels",
                f"Macro-F1 {c['f1_llm']:.2f} against {c['f1_base']:.2f}"
                + (f" (p = {_p(c['lead']['p_boot'])})" if c["lead"] else ""),
            ]
        )
    if len(c["tests"]):
        k, n = len(c["survivors"]), len(c["tests"])
        cards.append(
            [
                "H2 · Information",
                "Tone is associated with release-window Treasury moves",
                c["verdicts"]["h2"],
                f"{k} of {n} tests survive false-discovery control",
            ]
        )
    p = c["primary"]
    if p is not None:
        placebo = p.get("placebo_p")
        cards.append(
            [
                "H3 · Tradability",
                "A pre-registered next-day duration tilt beats chance",
                c["verdicts"]["h3"],
                f"Sharpe {p['sharpe']:.2f}" + (f", placebo p = {placebo:.2f}" if pd.notna(placebo) else ""),
            ]
        )
    a = c["audit"]
    if a.get("identify") and a.get("invariance"):
        exact = a["identify"].get("statement", next(iter(a["identify"].values())))["exact_month"]
        corr = a["invariance"]["corr_stance_score"]
        cards.append(
            [
                "H4 · Contamination",
                "Masked scores are stable; recognition risk remains",
                c["verdicts"]["h4"],
                f"Dates {exact:.0%} of masked statements, yet masked scores track raw ones (r = {corr:.2f})",
            ]
        )
    if not cards:
        return None
    v = c["verdicts"]
    pays = v.get("h3") == "Supported"
    subtitle = "Public-label accuracy and release-window associations; " + (
        "the primary delayed trade beats chance" if pays else "no delayed trading edge detected"
    )
    return {
        "id": "answers",
        "layout": "wide",
        "kicker": "The answers first",
        "title": "Four hypotheses, four answers",
        "subtitle": subtitle,
        "desk": "Use Claude to read the Fed faster and with evidence; "
        + (
            "size the tilt with costs and the placebo in mind."
            if pays
            else "do not expect a daily duration tilt on tone alone to pay."
        ),
        "source": "H1 labels may be in training; no post-cutoff human test. Only H3 was pre-registered; its corrected rerun is disclosed.",
        "notes": "Here are the answers before the evidence, one card per hypothesis. "
        + " ".join(f"{h.upper()}: {verdict.lower()}." for h, verdict in v.items()),
        "link": "#/event-study",
        "visual": {"kind": "answers", "cards": cards},
    }


def _divider(i):
    num, title, sub = SECTIONS[i]
    return {
        "id": f"part{num}",
        "layout": "divider",
        "kicker": f"Part {num}",
        "number": num,
        "title": title,
        "subtitle": sub,
        "notes": f"Part {num}: {title.lower()}.",
        "link": "#/overview",
    }


def _data(c):
    per_year = db.query(
        c["con"],
        "SELECT substr(release_date, 1, 4) AS year, doc_type, count(*) AS n FROM documents WHERE note IS NULL "
        "GROUP BY 1, 2 ORDER BY 1",
    )
    years = sorted(per_year["year"].unique().tolist())
    series = {
        t: [int(per_year[(per_year["year"] == y) & (per_year["doc_type"] == t)]["n"].sum()) for y in years]
        for t in ("statement", "minutes", "presser", "speech")
    }
    docs = c["docs"]
    provenance = {
        "statement": "time from text or recorded convention",
        "minutes": "attendance removed",
        "presser": "Chair's words only",
        "speech": "time from the Fed's feed",
    }
    min_words = settings()["sample"]["min_speech_words"]
    return {
        "id": "data",
        "kicker": "Data",
        "title": "Every Fed document since 2009",
        "subtitle": "Fed source text, recorded release times, and consistent cleaning",
        "number": f"{c['total']:,}",
        "number_label": f"statements, minutes, press conferences and Board speeches; {c['words'] / 1e6:.1f}M words",
        "chips": [
            f"{int(docs.loc[t, 'n']):,} {TYPE_LABELS[t]}; {provenance[t]}" for t in TYPE_LABELS if t in docs.index
        ],
        "desk": "One searchable store keeps source text, time provenance and every score, so a reading can be checked against its source.",
        "source": f"Fed calendar, source pages and speech feed; release-time conventions retained in the store. Speeches under {min_words} words excluded; SQLite FTS5 search.",
        "notes": "The corpus is collected from the Federal Reserve Board's own calendar, statements, minutes, transcripts and speech feed. "
        "Each release minute retains its source: text, the speech feed or a recorded convention. Press conferences keep the Chair's words, "
        f"minutes omit attendance lists, and speeches under {min_words} words are excluded. The counts and annual bars use documents without an exclusion note.",
        "link": "#/documents",
        "visual": {"kind": "corpus", "years": years, "series": series},
    }


def _timing(c):
    gap = settings()["markets"]["ambiguous_minutes"]
    return {
        "id": "timing",
        "kicker": "Timing",
        "title": "Release windows and trade entry",
        "subtitle": "Event windows measure repricing; returns begin only after entry",
        "number": "+1 day",
        "number_label": "primary entry lag after the first eligible ETF close",
        "chips": [
            "Event window: last pre-release Treasury fix to the first eligible later fix",
            f"Speech-feed buffer: {gap} minutes before either market close counts as after it",
            "Entry clock: first eligible ETF close, then one more trading day for the primary",
            "Return clock: first return after entry, never the return ending at that close",
        ],
        "desk": "The event study asks when yields adjust; the backtest asks whether a later executable position can use the signal.",
        "source": "Treasury and ETF clocks are shown in the diagram; the speech buffer guards both. align.py; tests/test_timing.py.",
        "notes": "A document's event window begins at the last Treasury fix before the first information is public, and ends at the first eligible fix after the full text is available. "
        "A statement has one fix-to-fix window; a press conference that straddles the Treasury fix spans two. "
        f"A feed-timestamped speech's availability is delayed by {gap} minutes for both the Treasury-window end and ETF-entry calculation. "
        "The exploratory entry is the first eligible ETF close; the primary waits one more trading day. A position earns only close-to-close returns after its entry. Weekends and holidays follow the observed trading calendar.",
        "link": "#/documents",
        "visual": {"kind": "timeline"},
    }


def _engine(c):
    llm = c["llm"]
    chips = ["Rubric v1: structured JSON and character-span evidence"]
    if not llm["level"]:
        lo, hi = _cost_range(c["con"])
        number, label = f"${lo:.0f} to ${hi:.0f}", "to score the corpus once through Message Batches, Haiku to Opus"
    else:
        number = f"{llm['share']:.2%}"
        label = f"mean document evidence-match share ({llm['level']:,} documents)"
        n, full, low = (
            c["con"]
            .execute(
                "SELECT count(*), sum(evidence_share = 1), min(evidence_share) FROM llm_records "
                "WHERE mode = 'level' AND coalesce(run_tag, '') = '' AND status = 'ok'"
            )
            .fetchone()
        )
        full = int(full or 0)
        chips += [
            f"{full:,} of {n:,} documents: every quote matched",
            f"{n - full:,} documents contain an unmatched quote",
            f"Lowest document match share: {low:.0%}",
        ]
    return {
        "id": "engine",
        "kicker": "Scoring and evidence verification",
        "title": "Every score comes with its evidence",
        "subtitle": "Claude supplies quoted spans; we verify each quote against the source",
        "number": number,
        "number_label": label,
        "chips": chips,
        "desk": "Matched spans make scores inspectable; quote matching alone does not establish that an economic interpretation is correct.",
        "source": "Typography-normalized source checks; mean document match share. A match verifies quotation fidelity, not economic interpretation.",
        "notes": "Each document is scored against six policy dimensions with a holistic stance, a continuous score, confidence and quoted evidence. "
        "Every returned quote is checked against the cleaned source with typography normalized; matched spans are located as character offsets. "
        f"The mean document evidence-match share is {(llm['share'] or 0):.2%} over {llm['level']:,} level records. "
        "Unmatched quotes are disclosed, not treated as verified evidence. Finding the quoted language proves its location, not the correctness of the model's economic judgment. Request provenance and spending are detailed on the next page.",
        "link": "#/pipeline",
        "visual": {"kind": "flow"},
    }


def _reading(c):
    if not c["llm_method"]:
        return None
    from .llm.scorer import verify_quotes

    row = db.query(
        c["con"],
        "SELECT r.key, r.parsed, d.text, d.release_date FROM llm_records r JOIN documents d ON d.doc_id = r.key "
        "WHERE r.mode = 'level' AND coalesce(r.run_tag, '') = '' AND r.status = 'ok' AND d.doc_type = 'statement' "
        "ORDER BY d.release_date DESC LIMIT 1",
    )
    if row.empty:
        return None
    r = row.iloc[0]
    parsed = json.loads(r["parsed"])
    text = r["text"] or ""
    spans = verify_quotes([e["quote"] for e in parsed.get("evidence", [])], text)["spans"]
    dims = {
        k: parsed.get(k)
        for k in (
            "policy_action",
            "forward_guidance",
            "inflation_assessment",
            "activity_labor_assessment",
            "risk_balance",
            "balance_sheet",
        )
    }
    when = date.fromisoformat(r["release_date"])
    score = parsed["stance_score"]
    stance = "hawkish" if score > 0.15 else "dovish" if score < -0.15 else "balanced"
    return {
        "id": "reading",
        "layout": "wide",
        "kicker": "One reading, end to end",
        "title": f"Claude reads the {when:%-d %B} statement as {stance}",
        "subtitle": "And shows, word for word, where the statement says so",
        "desk": "An analyst can check any score in seconds: the highlighted words are the evidence, located in the source.",
        "source": f"Statement of {when:%-d %B %Y}; Claude Opus 5.5, rubric v1; highlights are the evidence spans returned with the score.",
        "notes": f"Here is one real reading: the statement of {when:%-d %B}. Claude scores it {score:+.2f}, {stance}, with "
        f"confidence {parsed.get('confidence', 0):.2f}. The highlights are its evidence: the rate decision, the inflation "
        "language, the commitment to price stability. Each quote was found in the source text.",
        "link": f"#/tracker?sel={r['key']}",
        "visual": {
            "kind": "reading",
            "text": text[: max([s["end"] for s in spans] + [1200]) + 160],
            "spans": spans,
            "evidence": parsed.get("evidence", []),
            "dims": dims,
            "stance": score,
            "confidence": parsed.get("confidence"),
            "rationale": parsed.get("rationale", ""),
        },
    }


def _validity(c):
    if c["f1_llm"] is None:
        return None
    val = c["val"].set_index("method")
    base = " · ".join(
        f"{name} {val.loc[m, 'macro_f1']:.2f}"
        for m, name in (("supervised", "TF-IDF"), ("embedding", "Embeddings"), ("dictionary", "Dictionary"))
        if m in val.index
    )
    dict_f1 = val.loc["dictionary", "macro_f1"] if "dictionary" in val.index else float("nan")
    base_kappa = val.loc[val.index.isin(findings.BASELINES), "cohen_kappa"]
    kappa_reader = _label(base_kappa.idxmax()) if len(base_kappa) else "baseline"
    tuned = float(val.loc["roberta_tuned", "macro_f1"]) if "roberta_tuned" in val.index else None
    reference = (
        f" For reference, added after the results: a RoBERTa we fine-tuned on the same 1,984 labeled sentences "
        f"reaches {tuned:.2f}"
        + (
            ". Trained on the labels, a transformer does better still; Claude needed none."
            if tuned > c["f1_llm"]
            else ", still below Claude, which needed no labels at all."
        )
        if tuned is not None
        else ""
    )
    return {
        "id": "validity",
        "kicker": "Claude against three baselines",
        "title": "Higher agreement on public expert labels",
        "subtitle": "Public expert labels support H1; the post-cutoff human test was not run",
        "number": f"{c['f1_llm']:.2f}",
        "number_label": f"macro-F1 on {int(c['val']['n'].iloc[0])} sentences labeled by finance experts; the best "
        f"baseline reaches {c['f1_base']:.2f}",
        "compare": [
            [f"{c['f1_llm']:.2f}", f"Claude’s macro-F1 on {int(c['val']['n'].iloc[0])} expert-labeled sentences"],
            [f"{c['f1_base']:.2f}", "the best of the three simpler readers"],
        ],
        "compare_word": "against",
        "chips": [
            base,
            f"Kappa {c['kappa_llm']:.2f}; best baseline {c['kappa_base']:.2f} ({kappa_reader})",
            f"Lead {c['lead']['f1_diff']:+.2f}, 95% interval {c['lead']['ci_low']:+.2f} to {c['lead']['ci_high']:+.2f}"
            if c["lead"]
            else "",
            f"Fine-tuned RoBERTa {tuned:.2f}, for reference" if tuned is not None else "",
        ],
        "desk": "The baselines see words; Claude sees policy. The gap is largest on sentences that hedge, qualify or look ahead.",
        "source": "496 public expert labels may have appeared in training. The lead uses paired bootstrap; the masking audit partly addresses contamination.",
        "notes": "Four readers on the same 496 sentences that finance experts labeled hawkish, dovish or neutral. A "
        f"dictionary of policy words reaches {dict_f1:.2f}; two learned baselines, TF-IDF and sentence embeddings, reach "
        f"about {c['f1_base']:.2f}. Claude reaches {c['f1_llm']:.2f}, the highest agreement beyond chance of the four."
        + reference,
        "link": "#/validity",
        "visual": {"kind": "validity", "rows": c["val"].to_dict("records")},
    }


def _readers(c):
    """For reference, after the results: a RoBERTa fine-tuned on the labels the TF-IDF baseline learns from."""
    val = c["val"].set_index("method") if len(c["val"]) else None
    r = _meta(c["con"], "readers").get("roberta_tuned")
    if val is None or "roberta_tuned" not in val.index or not r or not r.get("search") or c["f1_llm"] is None:
        return None
    f1, llm, n = float(val.loc["roberta_tuned", "macro_f1"]), c["f1_llm"], int(val.loc["roberta_tuned", "n"])
    tfidf = float(val.loc["supervised", "macro_f1"]) if "supervised" in val.index else None
    cfg, epoch, types, seeds = r["chosen"]["config"], r["chosen"]["epoch"], r.get("types", {}), r.get("seed_macro_f1")
    method = c["method"] if c["method"].startswith("llm:") else c["llm_method"]
    claude = db.query(
        c["con"],
        "SELECT s.doc_id, s.score, d.doc_type FROM scores s JOIN documents d ON d.doc_id = s.doc_id "
        "WHERE s.method = ? AND d.doc_type IN ('statement', 'minutes', 'presser', 'speech')",
        (method,),
    )
    mine = r.get("scores", {})
    points = [[t, round(x, 3), round(mine[d], 3)] for d, x, t in claude.itertuples(index=False) if d in mine]
    lead = f1 - llm
    if lead > 0.01:
        title, verdict = "beats Claude", f"above Claude's {llm:.2f}"
    elif lead >= -0.01:
        title, verdict = "matches Claude", f"level with Claude's {llm:.2f}"
    else:
        title, verdict = "still trails Claude", f"below Claude's {llm:.2f}"
    names = {"statement": "statements", "minutes": "minutes", "presser": "press conferences", "speech": "speeches"}
    agree = " · ".join(f"{names[t]} {types[t]['pearson']:.2f}" for t in names if t in types)
    return {
        "id": "readers",
        "kicker": "For reference: a transformer trained on the same labels",
        "title": f"Trained on the labels, RoBERTa {title}",
        "subtitle": "The same 1,984 hand-labeled sentences improve accuracy; Claude needs no task-specific training",
        "number": f"{f1:.2f}",
        "number_label": f"macro-F1 on the same {n} test sentences; Claude, with no labels, reaches {llm:.2f}"
        + (f" and TF-IDF on the same labels {tfidf:.2f}" if tfidf is not None else ""),
        "chips": [
            f"Best of {len(r['search'])} settings on the same five folds: RoBERTa-{cfg['backbone'].split('-')[-1]}, "
            f"learning rate {cfg['lr']:.0e}".replace("e-0", "e-")
            + f", {epoch} epochs; added after the results",
            f"Five seeds averaged; alone {min(seeds):.2f} to {max(seeds):.2f}" if seeds else "",
            f"Agreement with Claude on documents, r: {agree}" if agree else "",
        ],
        "desk": "Labels buy accuracy on sentences like these; Claude needs none, reads whole documents and quotes its "
        "evidence."
        if lead > 0.01
        else "Even a transformer trained on the same labels does not beat Claude, which needed none.",
        "source": "RoBERTa (Liu et al. 2019) fine-tuned on the Trillion Dollar Words train split; settings chosen by "
        "five-fold CV; added after the results, outside H1.",
        "notes": "The obvious question after the last slide: what if, instead of an LLM, we train a transformer on the "
        "same 1,984 hand-labeled sentences the TF-IDF classifier learns from? We fine-tuned RoBERTa, tried "
        f"{len(r['search'])} settings on the same five folds, refit the best with five seeds and read the test "
        f"sentences once. It reaches {f1:.2f}, {verdict}"
        + (". " if not agree else f". On whole documents the two readers mostly agree: r = {agree}. ")
        + "Because it came after the results, it is a reference, not part of H1.",
        "link": "#/validity",
        "visual": {"kind": "readers", "points": points, "r": {t: types[t]["pearson"] for t in types}},
    }


def _tone(c):
    from . import api

    m = c["readings"].get("minutes")
    if not m:
        return None
    fed, nm = c["fed"], c["fed"].get("next_meeting")
    lean = (fed.get("market") or {}).get("t2y_minus_effr_bp")
    mood = c["pulse"].get("mood") or "balanced"
    idx = api.tone_index(c["method"], "minutes", c["con"])["series"].get("minutes", [])
    agrees = lean is not None and ((mood == "hawkish" and lean > 25) or (mood == "dovish" and lean < -25))
    return {
        "id": "tone",
        "kicker": "The index today",
        "title": f"Fed language is running {mood}",
        "subtitle": (f"Into the {date.fromisoformat(nm['date']):%-d %B} decision; " if nm else "")
        + "the latest minutes against every set since 2009",
        "number": _ordinal(m["percentile"]),
        "number_label": "percentile: the latest minutes against every set since 2009",
        "chips": [
            f"{label} {_ordinal(c['readings'][t]['percentile'])}"
            for t, label in (
                ("statement", "Statement"),
                ("presser", "Press conference"),
                ("speech", "Last 25 speeches"),
            )
            if t in c["readings"]
        ],
        "desk": f"Words lean {mood} and the 2-year sits {lean:+d} bp over the overnight rate: language and pricing point the same way."
        if agrees
        else f"Words lean {mood}; check whether pricing agrees before leaning on it.",
        "source": f"Tone by {_label(c['method'])}; percentile against the same document type since 2009.",
        "notes": f"Each dot is a set of minutes scored by {_label(c['method'])}; the line is a rolling median. The latest "
        f"minutes, released {date.fromisoformat(m['date']):%-d %B}, rank in the {_ordinal(m['percentile'])} percentile "
        "of all minutes since 2009.",
        "link": "#/overview",
        "visual": {"kind": "tone", "points": idx},
    }


def _tracker(c):
    cur = c["tracker"].get("current")
    if not cur or cur.get("similarity") is None:
        return None
    changed, median = round(100 * (1 - cur["similarity"])), round(100 * (1 - cur["median_similarity"]))
    month, act = f"{date.fromisoformat(cur['date']):%B}", {1: "hike", -1: "cut", 0: "hold"}[cur["action"]]
    decisions = c["tracker"]["decisions"]
    prev = decisions[-2]["doc_id"] if len(decisions) > 1 else None
    prev_dissents = [d for d in c["fed"].get("dissents", []) if d["doc_id"] == prev]
    sign = "+" if (cur["change_bp"] or 0) > 0 else ""
    chips = [f"{sign}{cur['change_bp'] or 0} bp to {cur['range_low']:.2f}–{cur['range_high']:.2f}%"]
    if c["fed"].get("current"):
        chips.append(f"Vote {c['fed']['current']['vote']}")
    if prev_dissents:
        chips.append(f"{len(prev_dissents)} dissents at the previous meeting wanted a {prev_dissents[0]['preferred']}")
    return {
        "id": "tracker",
        "kicker": "Decisions and wording",
        "title": f"The {month} {act} rewrote {changed}% of the statement",
        "subtitle": "A word-level redline of every decision against the one before",
        "number": f"{changed}%",
        "number_label": f"of the wording changed against the previous decision (median since 2009: {median}%)",
        "chips": chips,
        "desk": "Read the redline, not only the decision: new phrases and vanished dissents show how much conviction is behind a move.",
        "source": "Target range parsed from every statement ("
        + decision_mix(c["decision_counts"])
        + " since 2009); word-level diff against the previous decision.",
        "notes": f"Every statement is parsed for the decision and compared word by word with the previous one. The {month} "
        f"{act} rewrote {changed} percent of the statement against a median of {median} percent."
        + (
            f" At the previous meeting {len(prev_dissents)} members had dissented for a {prev_dissents[0]['preferred']}."
            if prev_dissents
            else ""
        ),
        "link": "#/tracker",
        "visual": {
            "kind": "wording",
            "median": median,
            "current": cur["doc_id"],
            "decisions": [
                {
                    "date": d["release_date"],
                    "changed": round(100 * (1 - d["similarity"]), 1),
                    "action": d["action"],
                    "high": d["range_high"],
                    "doc_id": d["doc_id"],
                }
                for d in decisions
                if d["similarity"] is not None
            ],
        },
    }


def _event(c):
    from . import api

    best, es = c["best"], c["es"]
    if best is None:
        return None
    pre = _same(es, best, outcome="pre_d2y", sample="all", control="none")
    ctrl = _same(es, best, outcome="d2y", sample="all", control="d3m")
    beyond = _same(es, best, outcome="d2y", sample="all", control="baseline")
    drift = _same(es, best, outcome="drift5_d2y", sample="all", control="none")
    group, shift = GROUP_NAMES[best["doc_type"]], best["regressor"] == "shift"
    chips = []
    if pre is not None:
        chips.append(f"Day before: t = {pre['t']:.2f} (placebo)")
    if ctrl is not None:
        chips.append(f"3-month bill as a surprise control: t = {ctrl['t']:.2f}")
    if beyond is not None:
        chips.append(f"TF-IDF tone as a control: t = {beyond['t']:.2f}")
    q = f", q = {best['q_bh']:.3f}" if pd.notna(best.get("q_bh")) else ""
    no_drift = drift is not None and abs(drift["t"]) < 2
    return {
        "id": "event",
        "kicker": "H2 · Exploratory association",
        "title": "Tone and 2-year release-window yield changes",
        "subtitle": f"{group.capitalize()}: {'change in the level score between releases' if shift else 'level of Claude score'}",
        "number": f"{best['beta_bp_per_sd']:+.1f} bp",
        "number_label": f"Associated 2-year move per SD of {'score change' if shift else 'score level'} (t = {best['t']:.2f}{q}; "
        f"{_label(best['method'])})",
        "chips": chips,
        "desk": (
            f"No detectable five-day drift (t = {drift['t']:.2f}); this does not establish full pricing."
            if no_drift
            else f"Five-day drift t = {drift['t']:.2f}; these associations do not identify a causal channel."
            if drift is not None
            else "These observational associations do not identify an exogenous communication shock."
        ),
        "source": f"OLS, HC1; {int(best['n'])} release windows. Shared news and overlapping releases limit causal interpretation.",
        "notes": "The lines show the average path of the 2-year around release days for the most dovish, middle and most "
        f"hawkish thirds of tone {best['regressor']} in {group}. One SD more hawkish accompanies a 2-year move of "
        f"{best['beta_bp_per_sd']:+.1f} basis points over the release window, t of {best['t']:.2f}."
        + (f" The day before: t of {pre['t']:.2f}." if pre is not None else "")
        + (f" With the 3-month bill as a control: t of {ctrl['t']:.2f}." if ctrl is not None else "")
        + (
            f" With the TF-IDF classifier's tone of the same documents as a control, Claude's tone still has a t of "
            f"{beyond['t']:.2f}; it adds an association beyond the TF-IDF score."
            if beyond is not None and beyond["t"] >= 2
            else ""
        ),
        "link": f"#/event-study?out=d2y&reg={best['regressor']}&focus={best['doc_type']}&curve={best['method']}",
        "visual": {
            "kind": "curves",
            "data": api.event_curves(best["doc_type"], best["method"], best["regressor"], c["con"]),
        },
    }


def _term(c):
    llm, main = c["llm_method"], c["main"]
    if not llm or not len(main):
        return None
    rows = main[
        (main["doc_type"] == "statement") & (main["regressor"] == "shift") & main["outcome"].isin(list(TENOR_NAMES))
    ]
    mine = rows[rows["method"] == llm]
    if mine.empty:
        return None
    top = mine.loc[mine["t"].idxmax()]
    methods = [m for m in ("supervised", "embedding", llm) if m in set(rows["method"])][-3:]
    tenor = TENOR_NAMES[top["outcome"]]
    chips = [
        f"{TENOR_NAMES[o]}: t = {mine[mine['outcome'] == o]['t'].iloc[0]:.2f}"
        for o in ("d2y", "d10y")
        if o != top["outcome"] and (mine["outcome"] == o).any()
    ]
    es = c["es"]
    alone = _same(es, top, outcome=top["outcome"], sample="no_presser", control="none")
    beside = _same(es, top, outcome=top["outcome"], sample="all", control="presser")
    if alone is not None:
        chips.append(f"Meetings without a press conference: t = {alone['t']:.2f} (n = {int(alone['n'])})")
    if beside is not None:
        chips.append(f"Press conference’s tone as a control: t = {beside['t']:.2f}")
    holds = alone is not None and alone["t"] >= 2
    title = "Statement tone shifts across the curve"
    subtitle = "Level-score changes between policy decisions; statement and conference windows overlap"
    return {
        "id": "term",
        "kicker": "Across the curve",
        "title": title,
        "subtitle": subtitle,
        "number": f"{top['beta_bp_per_sd']:+.1f} bp",
        "number_label": f"{tenor} move per standard deviation of the statement-to-statement shift in Claude’s score (t = {top['t']:.2f})",
        "chips": chips,
        "desk": (
            "The association also appears without conferences; daily fixes still cannot isolate an exogenous shock."
            if holds
            else "Daily fixes cannot isolate statement information from an overlapping press conference."
        ),
        "source": "Release-window changes on the shift since the previous decision (notices excluded); 95% intervals (HC1).",
        "notes": "This is the brief’s tone shift between consecutive statements. We regress each yield’s move over the "
        "statement window on the change in level score since the previous decision. The strongest association is at the "
        f"{tenor}; the result is descriptive, not a causal estimate."
        + (
            ""
            if c["fred"]
            else " The yields are the Treasury’s daily par curve, the same series FRED republishes; FRED was "
            "unavailable when we last ran the pipeline, and the next run tries it first again."
        ),
        "link": f"#/event-study?out={top['outcome']}&reg=shift&focus=statement",
        "visual": {"kind": "term", "rows": rows.to_dict("records"), "methods": methods},
    }


def _fdr(c):
    tests, surv, main = c["tests"], c["survivors"], c["main"]
    if not len(tests):
        return None
    is_llm = surv["method"].str.startswith("llm")
    k, n, k_llm = len(surv), len(tests), int(is_llm.sum())
    n_llm = int(tests["method"].str.startswith("llm").sum())
    reg = surv.loc[is_llm, "regressor"].mode().iloc[0] if k_llm else "shift"
    rows = main[(main["outcome"] == "d2y") & (main["regressor"] == reg)]
    methods = [m for m in ("supervised", "embedding", c["llm_method"]) if m and m in set(rows["method"])][-3:]
    qmin = float(tests["q_bh"].min())
    if k:
        title = (
            f"Claude accounts for {k_llm} of {k} surviving tests" if c["llm_method"] else f"{k} of {n} tests survive"
        )
        subtitle = f"Exploratory release-window associations; BH adjustment across {n} tests"
    elif qmin < 0.2:
        title, subtitle = (
            "The strongest association is above the cutoff",
            f"Corrected for {n} exploratory release-window tests",
        )
    else:
        title, subtitle = (
            "No release-window association survives",
            f"Corrected for {n} exploratory release-window tests",
        )
    return {
        "id": "fdr",
        "kicker": "Robustness",
        "title": title,
        "subtitle": subtitle,
        "number": f"{k} / {n}" if k else f"q = {qmin:.2f}",
        "number_label": "main release-window tests with Benjamini-Hochberg q below 0.10"
        if k
        else f"lowest q across {n} tests; 0.10 is the bar",
        "chips": [
            f"Claude: {k_llm} of {n_llm} tests",
            f"Dictionary, TF-IDF and embeddings: {k - k_llm} of {n - n_llm}",
            "Placebo, drift, controls and split samples are separate diagnostics",
        ],
        "desk": "False-discovery control addresses specification search, not shared news or causal identification.",
        "source": "Main grid: the four document types, every method and regressor, 3-month to 30-year yields and 2s10s; HC1; Benjamini-Hochberg.",
        "notes": f"We ran {n} exploratory release-window regressions and corrected for that family. {k} survive at a 10 percent "
        f"false-discovery rate, and {k_llm} of them use Claude’s reading. The chart shows the 2-year coefficients by "
        "document group for the three strongest readers.",
        "link": f"#/event-study?out=d2y&reg={reg}",
        "visual": {"kind": "coefs", "rows": rows.to_dict("records"), "methods": methods},
    }


def _backtest(c):
    bt, p = c["bt"], c["primary"]
    if not len(bt):
        return None
    n, hurdle = len(bt), float(bt["sharpe_hurdle"].iloc[0])
    passed = int((bt["dsr"] >= 0.95).sum())
    bars = bt.sort_values("sharpe", ascending=False)[
        ["run_id", "method", "doc_types", "signal", "sharpe", "dsr", "is_primary"]
    ]
    pays = c["verdicts"].get("h3") == "Supported"
    title = "The tested delayed tilt beats its placebo" if pays else "No reliable delayed trading edge"
    subtitle = "One primary specification; every exploratory variant is counted in the search"
    if p is not None:
        number = f"{p['sharpe']:.2f}"
        label = "Sharpe after costs: Claude on minutes and speeches, next-day entry, 5-day hold"
        placebo = f"Placebo p = {p['placebo_p']:.2f}; " if pd.notna(p.get("placebo_p")) else ""
        chips = [
            f"{placebo}probabilistic Sharpe {p['psr']:.0%}",
            f"{n} variants; expected-best no-skill Sharpe {hurdle:.2f}",
            f"{passed} pass DSR 95%; active AGG {p['active_bp']:+.0f} bp/year",
            f"21 Oct correction: Sharpe −0.23 → {p['sharpe']:.2f}; verdict unchanged",
        ]
        notes = (
            "The primary tilt was specified before results: Claude's level scores on minutes and speeches, next-day ETF entry, five-day hold, after costs. "
            f"Its Sharpe is {p['sharpe']:.2f}. All {n} tested variants are reported; {passed} pass the 95% deflated-Sharpe criterion, "
            f"against an expected-best no-skill Sharpe of {hurdle:.2f}. PSR compares the primary Sharpe with zero; DSR adjusts the comparison for the search. "
            "The primary test was rerun once on 21 October 2026 after code review restored the speech-availability buffer and decision-with-decision comparisons in the written design. "
            f"Sharpe changed from −0.23 to {p['sharpe']:.2f}; the verdict did not change. This daily-horizon result does not establish that every possible trading edge has disappeared."
        )
    else:
        number, label = f"{hurdle:.2f}", f"expected best Sharpe among {n} no-skill variants"
        chips = [
            f"{n} reported variants; {passed} pass the 95% DSR criterion",
            "Costs on both legs; entry only after the news",
        ]
        notes = f"The {n} variants are exploratory unless marked as the primary. Their deflated Sharpe is judged against an expected-best no-skill Sharpe of {hurdle:.2f}; {passed} pass the 95% criterion."
    return {
        "id": "backtest",
        "kicker": "Duration trading and selection bias",
        "title": title,
        "subtitle": subtitle,
        "number": number,
        "number_label": label,
        "chips": chips,
        "desk": "PSR tests Sharpe against zero; DSR raises the benchmark for the search across all variants.",
        "source": f"IEF minus SHY, ±1 year on AGG or IEI; {n} variants. DSR: Bailey and López de Prado. Rerun disclosure: DESIGN.md (21 Oct 2026).",
        "notes": notes,
        "link": "#/backtest",
        "visual": {"kind": "sharpes", "bars": bars.to_dict("records"), "hurdle": hurdle},
    }


def _audit(c):
    a = c["audit"]
    if not (a.get("identify") and a.get("invariance")):
        return None
    inv = a["invariance"]
    ident = a["identify"].get("statement", next(iter(a["identify"].values())))
    pts = db.query(
        c["con"],
        "SELECT json_extract(a.parsed, '$.stance_score') AS masked, json_extract(b.parsed, '$.stance_score') AS raw "
        "FROM llm_records a JOIN llm_records b ON b.key = a.key AND b.mode = 'level' AND coalesce(b.run_tag, '') = '' "
        "WHERE a.mode = 'level_anon'",
    ).dropna()
    return {
        "id": "audit",
        "kicker": "Memorization check",
        "title": "Recognition and score stability",
        "subtitle": "Masked scores track raw scores, a partial reassurance rather than proof against memorization",
        "number": f"r = {inv['corr_stance_score']:.2f}",
        "number_label": f"correlation of Claude’s scores with and without dates, names and rate levels ({inv['n']} documents)",
        "compare": [
            [f"{ident['exact_month']:.0%}", "of masked statements dated to the exact month: Claude recognizes them"],
            [
                f"r = {inv['corr_stance_score']:.2f}",
                f"between its scores with and without dates, names and rates, on {inv['n']} documents",
            ],
        ],
        "compare_word": "but",
        "chips": [
            f"Dates {ident['exact_month']:.0%} of masked statements to the exact month",
            f"Same overall stance on {inv['overall_stance_agreement']:.0%} of masked documents",
            f"{c['post_cutoff_docs']} documents released after the model’s knowledge cutoff so far",
        ],
        "desk": "The model knows Fed history, so trust rests on two checks: masked scores match, and the post-cutoff sample keeps growing.",
        "source": "Masking removes dates, names, numbers and rate levels; identification asks for the month of issue. After the HW2 GameStop audit.",
        "notes": "An honest worry: Claude has read history, including what markets did. With every date, name and rate "
        f"level masked, it still dates {ident['exact_month']:.0%} of statements to the exact month, so it recognizes them. "
        f"But its scores barely move when those details are removed: correlation {inv['corr_stance_score']:.2f}. The "
        "check partly addresses recognition risk; it cannot rule out contamination.",
        "link": "#/validity",
        "visual": {
            "kind": "audit",
            "points": pts[["raw", "masked"]].values.tolist(),
            "exact": ident["exact_month"],
            "corr": inv["corr_stance_score"],
        },
    }


def _fed(c):
    fed, nm = c["fed"], c["fed"].get("next_meeting")
    lean = (fed.get("market") or {}).get("t2y_minus_effr_bp")
    if not fed.get("current") or lean is None:
        return None
    cur = fed["current"]
    word = "more hikes" if lean > 25 else "cuts" if lean < -25 else "little change"
    chips = [
        f"Target {cur['range_low']:.2f}–{cur['range_high']:.2f}%",
        f"EFFR {fed['effr']['effr']:.2f}%" if fed.get("effr") else "",
        f"Next decision {date.fromisoformat(nm['date']):%-d %B}" if nm else "",
        f"Latest vote {cur['vote']}",
    ]
    return {
        "id": "fed",
        "kicker": "The Fed now",
        "title": f"The market leans to {word}",
        "subtitle": f"The 2-year sits {abs(lean)} bp {'above' if lean >= 0 else 'below'} the overnight rate",
        "number": f"{lean:+d} bp",
        "number_label": "2-year Treasury minus the effective fed funds rate",
        "chips": [x for x in chips if x],
        "desk": "Into the next decision, the curve prices more tightening than the overnight rate shows."
        if lean > 25
        else "Into the next decision, the curve prices cuts the overnight rate does not show yet."
        if lean < -25
        else "Into the next decision, the curve and the overnight rate roughly agree.",
        "source": "Effective fed funds rate and SOFR from the New York Fed; Committee roster from the minutes; 2-year from FRED or the Treasury.",
        "notes": "This is the live Fed-now page. The band is the target range, the blue line is where overnight money "
        "trades, and the orange line is the 2-year. The gap between the last two is a rough read of where the market "
        "thinks policy is going.",
        "link": "#/fed",
        "visual": {
            "kind": "policy",
            "path": fed["path"],
            "range_before": fed["range_before"],
            "rates": fed["rates"],
            "yields": fed["yields"],
        },
    }


def _architecture(c):
    counts = dict(
        c["con"]
        .execute(
            "SELECT 'yields', count(*) FROM yields UNION ALL SELECT 'scores', count(*) FROM scores "
            "UNION ALL SELECT 'events', count(*) FROM events UNION ALL SELECT 'regressions', count(*) FROM event_study "
            "UNION ALL SELECT 'variants', count(*) FROM backtests"
        )
        .fetchall()
    )
    return {
        "id": "architecture",
        "layout": "wide",
        "kicker": "Architecture",
        "title": "Ten stages, one store, three ways in",
        "subtitle": "Five public sources feed a pipeline that writes a single SQLite store",
        "desk": "Stages talk only through the store, so each can be rerun, tested or replaced on its own.",
        "desk_label": "Why it matters",
        "source": "Python 3.12 · pandas · statsmodels · scikit-learn · fastembed (ONNX) · Anthropic SDK · SQLite FTS5 · FastAPI · ECharts · Docker · Cloud Run",
        "notes": "The architecture in one picture. Five public sources feed ten pipeline stages. Every stage writes to a "
        "single SQLite store, and three front doors read it: the command line that runs the research, a REST API, and the "
        "dashboard, deployed as a read-only demo.",
        "link": "#/system",
        "visual": {
            "kind": "architecture",
            "sources": [
                ["Federal Reserve", "statements, minutes, transcripts, speeches"],
                ["FRED and U.S. Treasury", "yields, 3-month to 30-year"],
                ["New York Fed", "effective fed funds rate, SOFR"],
                ["Yahoo Finance", "SHY, IEI, IEF, TLT, AGG"],
                ["Trillion Dollar Words", "2,480 labeled sentences"],
            ],
            "stages": [
                ["collect", f"{c['total']:,} documents"],
                ["market", f"{counts.get('yields', 0):,} yield days"],
                ["events", f"{counts.get('events', 0):,} windows"],
                ["baselines", "3 simpler readers"],
                ["Claude", f"{c['llm']['level']:,} documents scored"],
                ["audit", "masking and invariance"],
                ["evaluate", f"{counts.get('regressions', 0):,} regressions"],
                ["backtest", f"{counts.get('variants', 0)} variants"],
                ["forecast", "the next decision, exploratory"],
                ["forward", "the frozen rules on new data"],
            ],
            "store": [
                f"{c['tables']} tables, schema v4",
                "FTS5 search over 4.5M words",
                f"{counts.get('scores', 0):,} scores",
            ],
            "serve": [
                ["Command line", "fomc run, llm-*, slides"],
                ["REST API", f"{c['endpoints']} endpoints, ETags on reads"],
                ["Dashboard", "live demo, no build step"],
            ],
        },
    }


def _engineering(c):
    f, llm = c["facts"], c["llm"]
    tiles = [
        ["1 command", "fomc run respects the research freeze; stages whose inputs did not change are skipped"],
        [f"{f.get('raw_files', 0):,}", "source files cached by URL: nothing is downloaded twice"],
        [f"{llm['records']:,}", "Claude records keyed by a hash of prompt, schema and text: nothing is paid for twice"],
        [
            f"${llm['cost']:.0f}",
            f"for {llm['level']:,} documents and every check, through Message Batches at half price",
        ],
        [
            f"{f.get('tests', 0)}",
            "offline tests recorded in the snapshot: timing, scoring, API, migrations, hosted mode",
        ],
        [f"{c['tables']}", "tables in one SQLite file, versioned schema with automatic migrations"],
        [f"{c['endpoints']}", "JSON endpoints behind the dashboard; read-only ones revalidate with ETags"],
        ["0", "keys on the public demo: read-only mode locks settings, scoring and labeling"],
    ]
    return {
        "id": "engineering",
        "layout": "wide",
        "kicker": "Engineering",
        "title": "Built to be rerun and extended",
        "subtitle": "Cached inputs avoid repeat calls; the frozen study stays fixed as new documents arrive",
        "desk": "Anyone on the team can rebuild the deck from scratch with two commands: make run, then make slides.",
        "desk_label": "Why it matters",
        "source": "GitHub Actions runs lint, tests and front-end checks on every push and redeploys the demo on Cloud Run every "
        "evening.",
        "notes": "A few engineering choices that matter. One command rebuilds everything, and stages whose inputs have not "
        "changed are skipped. Downloads and Claude calls are cached by content; new documents may need paid scoring. The test suite "
        "runs on every push, and the public demo carries no keys.",
        "link": "#/system",
        "visual": {"kind": "tiles", "tiles": tiles},
    }


def _screens(c):
    return {
        "id": "screens",
        "layout": "wide",
        "kicker": "The product",
        "title": "A dashboard a rates desk could open every morning",
        "subtitle": "Source documents, clearer comparisons and a linked duration workspace",
        "desk": "Everything in this deck is one click away in the live app, with the source documents behind every number.",
        "desk_label": "Try it",
        "source": "Live demo: fedtone.web.app (read-only); run locally with make serve.",
        "notes": "This is the product: a home page with the Fed pulse and the four findings, the Fed-now pages with rates, "
        "the Committee (click a member for their background, the tone of every speech and their dissents) and every "
        "decision redlined, and the research pages. It is live; we can switch to it now.",
        "link": "#/overview",
        "visual": {
            "kind": "screens",
            "shots": [
                ["Documents", "/static/img/documents.jpg"],
                ["Fed now", "/static/img/fed.jpg"],
                ["Duration", "/static/img/duration.jpg"],
                ["Pipeline", "/static/img/pipeline.jpg"],
            ],
        },
    }


def _duration_workspace(c):
    return {
        "id": "duration-workspace",
        "layout": "wide",
        "kicker": "The duration workflow",
        "title": "From a Fed document to duration exposure",
        "subtitle": "A traceable rule replay connects evidence with sizing and its historical test",
        "source": "api/duration/context; duration.py; frozen primary reader and entry rules. This is one document's rule, not the combined backtest position.",
        "notes": "Open a document and choose Explore duration. The workspace reads its score from the frozen primary model. "
        "It standardizes only against earlier eligible documents of the same type. The fixed rule maps that z-score "
        "to a share of the duration budget, as in the historical test. The user supplies capital, portfolio duration "
        "and the budget; an equal-dollar ETF overlay then gives dollar DV01, round-trip trading cost and parallel-shock "
        "P&L. Non-primary types, insufficient history and low "
        "policy relevance receive no rule-sized trade. Manual overrides remain labeled. Historical and forward tests "
        "stay one click away, including the negative H3 result. This tool does not add evidence of profitability.",
        "link": "#/duration",
        "visual": {
            "kind": "steps",
            "steps": [
                ["Read the evidence", "A scored Fed document, its source and policy-relevant evidence spans"],
                ["Replay the fixed rule", "Earlier same-type peers, a standardized score and explicit delayed entry"],
                ["Translate to money", "User capital and duration budget, dollar DV01, ETF legs and round-trip cost"],
                ["Challenge the result", "Parallel shocks, the stored historical test and prospective evaluation"],
            ],
        },
    }


def _brief_audit(c):
    return {
        "id": "brief-audit",
        "layout": "wide",
        "kicker": "Assignment coverage",
        "title": "Topic 4 coverage and its limits",
        "subtitle": "Seven functional requirements have evidence, with profitability reported honestly",
        "source": "docs/ASSIGNMENT.md; docs/BRIEF_AUDIT.md; read-only audit of the frozen store.",
        "notes": "The seven components in the brief are implemented. A negative trading result does not mean the "
        "backtest is missing. The corpus covers the four requested document types. Claude scores have a defined rubric "
        "and evidence spans. Dictionary and sentence-embedding baselines share an expert-labeled test. Five Treasury "
        "tenors use the FRED series with an official Treasury fallback. AGG and IEI views expose the delayed duration "
        "tilt, including costs and multiple-testing controls. Daily windows respect public-release times but cannot "
        "identify minute-by-minute pricing. Minutes, speeches and statement shifts are all tested. Optional post-cutoff "
        "human annotation was not run and is not presented as completed.",
        "link": "#/system",
        "visual": {
            "kind": "table",
            "columns": ["Requirement", "Delivered evidence", "Boundary"],
            "rows": [
                ["Four Fed text types", f"{c['total']:,} documents", "Board speeches only"],
                ["Claude rubric and evidence", f"{c['llm']['level']:,} main readings", "Recognition remains possible"],
                ["Simpler text baselines", "Dictionary, TF-IDF, embeddings", "Public expert labels"],
                ["Treasury curve test", "3m, 2y, 5y, 10y and 30y", "Treasury fallback disclosed"],
                ["Bond portfolio duration tilt", f"{len(c['bt'])} variants, AGG / IEI", "Fixed risk assumptions"],
                ["Release-time backtest", "Delayed entry, costs, placebos", "Daily data, not ticks"],
                ["Minutes, speeches and shifts", "Primary and exploratory tests", "No reliable H3 edge"],
            ],
        },
    }


def _takeaways(c):
    cards = []
    if c["f1_llm"] is not None:
        val = c["val"].set_index("method")
        tuned = float(val.loc["roberta_tuned", "macro_f1"]) if "roberta_tuned" in val.index else None
        ahead = tuned is not None and tuned > c["f1_llm"] + 0.01  # a model trained on the labels reads them better
        cards.append(
            [
                "Higher agreement on public expert labels",
                f"Public-label macro-F1 {c['f1_llm']:.2f} against {c['f1_base']:.2f} for the best baseline"
                + (f" without task-specific training (trained RoBERTa: {tuned:.2f}); " if ahead else "; ")
                + "no post-cutoff human validation was run.",
            ]
        )
    if len(c["tests"]):
        k, n = len(c["survivors"]), len(c["tests"])
        k_llm = int(c["survivors"]["method"].str.startswith("llm").sum())
        cards.append(
            [
                "Tone accompanies release-window repricing",
                f"{k} of {n} exploratory release-window tests survive adjustment, {k_llm} on Claude’s reading. "
                "Shared news and overlapping releases prevent a causal interpretation.",
            ]
        )
    p = c["primary"]
    if p is not None:
        placebo = p.get("placebo_p")
        cards.append(
            [
                "No delayed trading edge detected",
                f"The pre-registered trade has a Sharpe of {p['sharpe']:.2f}"
                + (f" (placebo p = {placebo:.2f})" if pd.notna(placebo) else "")
                + "; no variant clears the luck hurdle.",
            ]
        )
    return {
        "id": "takeaways",
        "layout": "wide",
        "kicker": "Takeaways",
        "title": "Three things a rates desk can use",
        "subtitle": "What the evidence supports, and how to use it",
        "desk": "Use the evidence-linked index for inspection; the tested daily tilt does not establish an investable edge.",
        "source": "Frozen store results. Public expert labels may be in training; masking provides partial reassurance only.",
        "notes": "Three takeaways. Claude outperforms the stated baselines on public expert sentences, with no "
        "task-specific training, but public-label exposure remains possible. Tone is associated with release-window "
        "yield changes. The tested delayed duration tilt does not beat chance; this does not prove full market pricing.",
        "link": "#/overview",
        "visual": {"kind": "cards", "cards": cards},
    }


def _limits(c):
    inv = c["audit"].get("invariance", {})
    p = _p(c["lead"]["p_boot"]) if c["lead"] else "unavailable"
    corr = f"{inv['corr_stance_score']:.2f}" if inv else "unavailable"
    cards = [
        [
            "Daily closes, not ticks",
            "Release windows use the 3:30 p.m. Treasury fix; intraday data would sharpen the statement tests.",
        ],
        [
            "Small post-cutoff sample",
            f"{c['post_cutoff_docs']} documents since the configured post-cutoff date, {settings()['splits']['post_cutoff'][0]}; no independent human reference.",
        ],
        [
            "No post-cutoff human test",
            f"{c['items']} sentences have model predictions. No post-cutoff human or cross-model validation was performed.",
        ],
        [
            "Public labels may be familiar",
            "Expert labels may be in the model's training data. Masking dates and names partly addresses this risk.",
        ],
    ]
    return {
        "id": "limits",
        "layout": "wide",
        "kicker": "Limits and next steps",
        "title": "What would change our minds, and what we do next",
        "subtitle": "H1 is supported on public expert labels; independent human validation remains absent",
        "desk": "Independent labels, intraday yields, and more frozen-rule releases would strengthen the evidence.",
        "desk_label": "Next",
        "source": f"H1 on public expert labels: p = {p}. Masked/raw r = {corr} partly addresses possible training exposure.",
        "notes": "Limits, stated plainly. We use daily closes; intraday data would sharpen the statement tests. The sample "
        "after the configured cutoff is still small. The post-cutoff human test was not run. H1 is supported on the "
        "public expert labels, which may have appeared in training. The masking audit only partly addresses that risk.",
        "link": "#/label",
        "visual": {"kind": "cards", "cards": cards},
    }


def _closing(c):
    return {
        "id": "closing",
        "layout": "closing",
        "kicker": f"{c['proj']['group']} · {c['proj']['course']}",
        "title": "Thank you",
        "subtitle": "Questions and discussion",
        "team": c["proj"]["team"],
        "url": "fedtone.web.app",
        "notes": "Thank you. Happy to take questions, or to open any page of the dashboard live.",
        "link": "#/overview",
    }


def _forecast(c):
    f = c["forecast"]
    if not f.get("n"):
        return None
    ins, oos = f["in_sample"], f["out_of_sample"]
    helps = oos["diff"] < 0 and oos["p_boot"] < 0.05
    year = oos["start"][:4]
    return {
        "id": "forecast",
        "kicker": "The next decision",
        "title": "Adding tone improves the held-out forecast" if helps else "No forecast gain from tone detected",
        "subtitle": "Exploratory expanding-window forecasts use only earlier decisions",
        "number": f"{ins['r2_market']:.2f}",
        "number_label": f"market-only in-sample R² across {f['n']} decisions; pre-meeting 3-month and 2-year spreads over policy",
        "chips": [
            f"With Claude's tone: R² {ins['r2_both']:.2f} (F-test p = {ins['p']:.2f})",
            f"Forecasts from {year}: MSE {oos['mse_both']:.3f} with tone, {oos['mse_market']:.3f} without (p = {oos['p_boot']:.2f})",
            f"{oos['n']} forecasts, {oos['moves']} of them moves",
            "Exploratory: added after the results",
        ],
        "desk": "Adding tone reduces real-time forecast error in this sample; independent forward evaluation remains necessary."
        if helps
        else "Adding tone does not reduce real-time forecast error in this sample; the test is exploratory.",
        "source": "Decisions and pre-meeting yields/tone; linear model, HC1. MSE: mean squared error for cut/hold/hike (−1/0/+1).",
        "notes": f"Does Claude's reading add to what the market already prices about the next decision? For each of the {f['n']} "
        "decisions since 2009 we model the decision (cut, hold or hike) on the 3-month bill and 2-year over the policy rate at the "
        "last close before it, and on the tone of the latest minutes, the speeches of the previous 60 days and the previous "
        f"statement. The market's lean alone explains {ins['r2_market']:.0%}; tone adds a little in sample. In real time, "
        f"forecasting every decision from {year} with only earlier data, adding tone "
        + ("lowers the error." if oos["diff"] < 0 else "does not lower the error.")
        + " We added this test after the results, so treat it as exploratory.",
        "link": "#/forecast",
        "visual": {"kind": "forecast", "meetings": f["meetings"]},
    }


def build(con, deck: str = "main") -> dict:
    """One integrated story; the former technical-only sequence remains an explicit legacy view."""
    from . import story_technical as tech

    c = _context(con)
    if deck == "technical":
        return _finish(c, tech.slides(c), deck)
    parts = [
        [_primer(c), _brief(c), _course_links(c), _answers(c), _data(c), _timing(c)],
        [tech.rubric_slide(c), _engine(c), tech.engine(c), _reading(c), tech.baselines(c),
         _local_training(c), tech.search(c), _validity(c), tech.validity_tests(c),
         tech.confusions(c), _readers(c), _audit(c), tech.reliability(c)],
        [_tone(c), _tracker(c), tech.event_spec(c), _event(c), _term(c), tech.robustness(c),
         _fdr(c), tech.backtest_math(c), _backtest(c), _duration_workspace(c)],
        [_fed(c), _forecast(c), tech.forecast(c), tech.forward(c), _architecture(c),
         tech.store(c), tech.serving(c), tech.deploy(c), tech.tests(c), _screens(c)],
        [_beyond(c), _brief_audit(c), _takeaways(c), _limits(c), _closing(c)],
    ]  # fmt: skip
    slides = [_cover(c), _agenda(c)]
    for part, members in enumerate(parts):
        for slide in members:
            if slide:
                slide["part"] = part
                slides.append(slide)
    return _finish(c, slides, deck)


# How each content slide is laid out, chosen for what it has to show: "banner" puts the number and its facts in a
# band over a full-width visual (time series, long rows of bars, a flow); "mirror" puts the visual first; "compare"
# sets two numbers against each other. Slides not named here keep their own layout or the standard one.
LAYOUTS = {
    "data": "banner", "engine": "mirror", "validity": "compare", "readers": "mirror", "tone": "banner",
    "term": "mirror", "backtest": "banner", "audit": "compare", "fed": "banner", "forecast": "mirror",
    "tech-windows": "banner", "tech-rubric": "mirror", "tech-search": "mirror", "tech-confusions": "banner",
    "tech-reliability": "mirror", "tech-robustness": "banner", "tech-backtest": "mirror", "tech-forecast": "mirror",
}  # fmt: skip
# The "For the desk" band only where the trading consequence is the point of the slide; elsewhere its line goes to the
# speaker notes and the visual takes the room.
DESK = {"tone", "event", "backtest", "fed", "forecast", "limits", "tech-backtest", "tech-forward"}


def _finish(c, slides: list, deck: str) -> dict:
    """Number the slides that have data, lay each out, and set true minus signs in every displayed number."""
    slides = [s for s in slides if s]
    for i, s in enumerate(slides, 1):
        s["n"] = i
        s.setdefault("layout", "standard")
        if s["layout"] == "standard" and s.get("id") in LAYOUTS:
            s["layout"] = LAYOUTS[s["id"]]
        if s["layout"] == "compare" and not s.get("compare"):
            s["layout"] = "standard"
        if s.get("desk") and s["layout"] not in ("cover", "closing", "divider") and s.get("id") not in DESK:
            s["notes"] = f"{s.get('notes', '')} {s.get('desk_label', 'For the desk')}: {s['desk']}".strip()
            s["desk"] = None
        for pair in s.get("compare") or []:
            pair[0], pair[1] = MINUS.sub("−", pair[0]), MINUS.sub("−", pair[1])
        for k in ("title", "subtitle", "number", "number_label", "desk"):
            if isinstance(s.get(k), str):
                s[k] = MINUS.sub("−", s[k])
        if s.get("chips"):
            s["chips"] = [MINUS.sub("−", x) if x else x for x in s["chips"]]
        if s.get("visual", {}).get("kind") in ("answers", "cards"):
            s["visual"]["cards"] = [[MINUS.sub("−", x) for x in card] for card in s["visual"]["cards"]]
        if s.get("visual", {}).get("kind") == "table":
            s["visual"]["rows"] = [[MINUS.sub("−", x) for x in row] for row in s["visual"]["rows"]]
    agenda = next((s for s in slides if s["id"] == "agenda"), None)
    if agenda:
        agenda["visual"]["rows"] = []
        for part, (title, description) in enumerate(MAIN_SECTIONS):
            members = [s for s in slides if s.get("part") == part]
            if members:
                agenda["visual"]["rows"].append([title, description, f"{members[0]['n']}-{members[-1]['n']}"])
    return {
        "deck": deck,
        "method": c["method"],
        "as_of": date.today().isoformat(),
        "team": c["proj"]["team"],
        "slides": slides,
    }
