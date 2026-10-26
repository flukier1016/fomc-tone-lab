"""Market data: Treasury yields across the curve (FRED) and bond ETF prices (Yahoo Finance).

Yields come from FRED's constant-maturity series (DGS3MO, DGS2, DGS5, DGS10, DGS30), as the project
brief asks. FRED republishes the Federal Reserve's H.15 release, which takes these yields from the
Treasury's daily par yield curve (quotes near 3:30 p.m. ET); if FRED cannot be reached, the stage reads
the same curve from home.treasury.gov and records which source it used.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

from . import http
from .config import PROCESSED, ensure_dirs, settings

UST_CSV = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={y}&page&_format=csv"
)


FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"


def parse_fred(raw: bytes, series: str) -> pd.Series:
    """One FRED CSV (observation_date or DATE, then the series; '.' or blank for no quote)."""
    head = raw.lstrip()[:40].lower()
    if not (head.startswith(b"observation_date") or head.startswith(b"date")):
        raise ValueError(f"FRED did not return a CSV for {series} (maintenance page or error)")
    df = pd.read_csv(io.BytesIO(raw), na_values=["."])
    df.columns = ["date", series]
    return df.set_index(pd.to_datetime(df["date"]))[series].astype(float)


def fred_yields(start: str) -> pd.DataFrame:
    cols = {
        tenor: parse_fred(http.get(FRED_CSV.format(series=sid, start=start), refresh=True), sid)
        for tenor, sid in settings()["markets"]["fred_series"].items()
    }
    out = pd.DataFrame(cols).dropna(how="all").sort_index()
    out.index.name = "Date"
    return out


def treasury_yields(start_year: int, end_year: int | None = None) -> pd.DataFrame:
    """Daily par yields in percent, one column per tenor (quotes near 3:30 p.m. ET)."""
    end_year = end_year or date.today().year
    frames = []
    for year in range(start_year, end_year + 1):
        raw = http.get(UST_CSV.format(y=year), refresh=year >= date.today().year)
        frames.append(pd.read_csv(io.BytesIO(raw)))
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    df = df.set_index("Date").sort_index()
    return df.loc[~df.index.duplicated(), settings()["markets"]["ust_tenors"]]


def etf_prices(start: str) -> pd.DataFrame:
    """Dividend-adjusted closes (total return), 4:00 p.m. ET."""
    import yfinance as yf

    tickers = settings()["markets"]["etfs"]
    px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    return px[tickers].dropna(how="all")


def build() -> str:
    """Write yields and ETF prices; return where the yields came from."""
    ensure_dirs()
    start_year = settings()["sample"]["fomc_start_year"] - 1
    try:
        yields, source = fred_yields(f"{start_year}-01-01"), "FRED (DGS3MO, DGS2, DGS5, DGS10, DGS30)"
    except (OSError, ValueError, KeyError) as exc:  # FRED down or changed: same curve from the Treasury
        yields = treasury_yields(start_year)
        source = f"U.S. Treasury par yield curve (FRED unavailable: {str(exc)[:80]})"
    yields.to_csv(PROCESSED / "ust_par_yields.csv")
    (PROCESSED / "yield_source.txt").write_text(source)
    try:
        etfs = etf_prices(f"{start_year}-12-01")
        if etfs.empty:
            raise ValueError("no prices returned")
        etfs.to_csv(PROCESSED / "etf_prices.csv")
    except Exception as exc:  # Yahoo turns some cloud runners away: keep the closes already on file
        print(f"ETF closes not refreshed ({str(exc)[:80]}); keeping the last ones")
    return source


def load_yields() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "ust_par_yields.csv", index_col=0, parse_dates=True)


def load_etfs() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "etf_prices.csv", index_col=0, parse_dates=True)
