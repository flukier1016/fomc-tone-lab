"""Public source badges with roles and actual store dates, never credentials."""

import json


def yield_source(con) -> str:
    row = con.execute("SELECT value FROM meta WHERE key='yield_source'").fetchone()
    if not row or row[0] is None:
        return ""
    try:
        value = json.loads(row[0])
        return value if isinstance(value, str) else ""
    except (ValueError, TypeError):
        return str(row[0])


def sources(con) -> list[dict]:
    def latest(table):
        return con.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]

    actual = yield_source(con)
    fred = str(actual).startswith("FRED")
    treasury = "treasury" in actual.lower()
    count, last = con.execute("SELECT count(*), MAX(release_date) FROM documents WHERE note IS NULL").fetchone()
    labels = con.execute("SELECT MAX(n) FROM validity").fetchone()[0]
    common = [
        (
            "fed",
            "FED",
            "Federal Reserve",
            "Documents",
            "https://www.federalreserve.gov/monetarypolicy/fomc.htm",
            last,
            f"{count:,} documents",
        ),
        (
            "fred",
            "FRED",
            "FRED",
            "Yield series",
            "https://fred.stlouisfed.org/series/DGS10",
            latest("yields") if fred else None,  # a date only for the provider the stored yields came from
            "Active source" if fred else "Primary series, fallback used" if treasury else "Primary series",
        ),
        (
            "treasury",
            "UST",
            "U.S. Treasury",
            "Yield fallback",
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
            latest("yields") if treasury else None,
            "Active source" if treasury else "Fallback available",
        ),
        (
            "yahoo",
            "YF",
            "Yahoo Finance",
            "ETF prices",
            "https://finance.yahoo.com/quote/IEF/history/",
            latest("etf_prices"),
            "Adjusted closes",
        ),
        (
            "nyfed",
            "NYF",
            "New York Fed",
            "Overnight rates",
            "https://www.newyorkfed.org/markets/reference-rates",
            latest("policy_rates"),
            "EFFR and SOFR",
        ),
        (
            "tdw",
            "TDW",
            "Trillion Dollar Words",
            "Expert labels",
            "https://huggingface.co/datasets/gtfintechlab/fomc_communication",
            None,
            f"{int(labels):,} test sentences" if labels else "Expert evaluation set",
        ),
    ]
    return [dict(id=k, mark=m, name=n, role=r, url=u, as_of=d, detail=t) for k, m, n, r, u, d, t in common]
