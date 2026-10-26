"""Read-only evidence checklist for the seven Topic 4 requirements."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fomc import db, provenance

ROOT = Path(__file__).resolve().parents[1]


def audit(con):
    counts = dict(con.execute("SELECT doc_type,count(*) FROM documents WHERE note IS NULL GROUP BY doc_type"))
    method = con.execute("SELECT method FROM backtests WHERE is_primary=1 LIMIT 1").fetchone()
    method = method[0] if method else ""
    scored = con.execute("SELECT count(*) FROM scores WHERE method=?", (method,)).fetchone()[0]
    verified = con.execute(
        "SELECT count(*),avg(evidence_share) FROM llm_records WHERE mode='level' AND status='ok'"
    ).fetchone()
    baselines = dict(
        con.execute("SELECT method,n FROM validity WHERE method IN ('dictionary','supervised','embedding')")
    )
    curve = con.execute(
        "SELECT count(*) FROM yields WHERE t3m IS NOT NULL AND t2y IS NOT NULL "
        "AND t5y IS NOT NULL AND t10y IS NOT NULL AND t30y IS NOT NULL"
    ).fetchone()[0]
    source = provenance.yield_source(con).split(" (", 1)[0] or "unavailable"
    variants = con.execute("SELECT count(*) FROM backtests").fetchone()[0]
    primary = con.execute("SELECT sharpe,placebo_p FROM backtests WHERE is_primary=1").fetchone()
    windows = con.execute(
        "SELECT count(*) FROM events WHERE avail_ts IS NOT NULL AND etf_entry_next IS NOT NULL"
    ).fetchone()[0]
    shifts = con.execute("SELECT count(*) FROM backtests WHERE signal='shift'").fetchone()[0]
    groups = [r[0] for r in con.execute("SELECT DISTINCT doc_types FROM backtests")]
    rows = [
        (
            "Fed corpus: four document types",
            all(counts.get(k, 0) > 0 for k in ("statement", "minutes", "presser", "speech")),
            str(counts),
            "The speech corpus covers Board governors, not all Reserve Bank presidents.",
        ),
        (
            "Claude rubric with evidence spans",
            scored > 0 and verified[0] > 0,
            f"{scored} frozen-reader scores; {verified[0]} verified level records",
            "Evidence matching does not prove the absence of model memory.",
        ),
        (
            "Dictionary and embedding baselines",
            len(baselines) == 3 and all(n > 0 for n in baselines.values()),
            str(baselines),
            "Public expert labels may have been seen in training; post-cutoff human validation was not run.",
        ),
        (
            "Treasury yields across the curve",
            curve > 0,
            f"{curve} complete five-tenor dates; actual source: {source}",
            "The official Treasury fallback replaces unavailable FRED downloads. Badges disclose the active provider.",
        ),
        (
            "Treasury / aggregate-bond duration tilt",
            variants > 0 and primary is not None,
            f"{variants} stored variants; AGG and IEI portfolio views",
            "Fixed ETF durations are assumptions. The negative primary result remains part of the answer.",
        ),
        (
            "Public-release timing and executable delay",
            windows > 0,
            f"{windows} aligned delayed-entry windows",
            "Daily closes respect release timing but do not measure minute-by-minute price discovery.",
        ),
        (
            "Minutes, speeches and statement tone shifts",
            shifts > 0 and "minutes+speech" in groups and "statement" in groups,
            f"{shifts} shift-signal variants; minutes+speech primary",
            "No reliable delayed trading edge was found under the frozen rules.",
        ),
    ]
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "rows": [dict(requirement=k, covered=bool(ok), evidence=e, limit=boundary) for k, ok, e, boundary in rows],
        "primary_sharpe": primary[0] if primary else None,
        "primary_placebo_p": primary[1] if primary else None,
        "research_recomputed": False,
    }


def main():
    con = db.connect()
    result = audit(con)
    con.close()
    out = ROOT / "qa" / "product_linkage"
    out.mkdir(parents=True, exist_ok=True)
    (out / "brief_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    checked = datetime.fromisoformat(result["checked_at"])
    md = (
        f"# Topic 4 coverage audit\n\nRead-only inspection of the frozen store on {checked:%-d %B %Y}. "
        "Functional coverage and positive research results are different questions.\n\n"
        "| Requirement | Coverage | Evidence | Boundary |\n|---|---|---|---|\n"
    )
    md += "\n".join(
        f"| {r['requirement']} | {'Covered' if r['covered'] else 'Missing evidence'} | {r['evidence']} | {r['limit']} |"
        for r in result["rows"]
    )
    md += (
        f"\n\nThe primary Sharpe is {result['primary_sharpe']:.4f} "
        f"and the placebo p-value {result['primary_placebo_p']:.3f}. "
        "The tested trading rule is not supported. The test and negative result are implemented and reported.\n"
    )
    md += (
        "\nThe Duration section links document evidence and prior-only rule replay to exposure sizing, "
        "the frozen historical test and forward evaluation. Its custom scenario is a what-if illustration. "
        "No research stage was rerun.\n"
    )
    (ROOT / "docs" / "BRIEF_AUDIT.md").write_text(md)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
