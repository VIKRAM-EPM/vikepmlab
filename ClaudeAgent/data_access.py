"""
data_access.py

Pure-Python/pandas data layer for the NASDAQ financial data-quality agent.
No Claude/API dependency here on purpose: these functions are the "ground
truth" tools the agent calls, and they should be independently testable
and correct before an LLM ever touches them.

Dataset: SEC EDGAR-derived 10-K/10-Q fundamentals for 2,600+ NASDAQ
companies, 2023-2027 fiscal periods.
"""

from __future__ import annotations

import pandas as pd

CSV_PATH = "data.csv"

_df: pd.DataFrame | None = None


def load_data(path: str = CSV_PATH) -> pd.DataFrame:
    """Load and lightly normalize the dataset. Cached at module level."""
    global _df
    if _df is not None:
        return _df
    df = pd.read_csv(path)
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    df["period_start_date"] = pd.to_datetime(df["period_start_date"])
    df = df.sort_values(["ticker", "period_end_date"]).reset_index(drop=True)
    _df = df
    return df


def _select_period(df: pd.DataFrame, ticker: str, fiscal_year: int, fiscal_period: str) -> pd.DataFrame:
    return df[
        (df.ticker == ticker.upper())
        & (df.fiscal_year == float(fiscal_year))
        & (df.fiscal_period == fiscal_period.upper())
    ]


def check_balance_sheet(ticker: str, fiscal_year: int, fiscal_period: str) -> dict:
    """
    Verify the fundamental accounting identity: Assets = Liabilities + Equity.

    Returns the raw figures, the dollar and percentage delta, and whether
    the mismatch exceeds a 1% tolerance. Does NOT classify the mismatch as
    an error -- that requires judgment the agent applies using
    get_period_history (e.g. negative equity is normal for many SPACs).
    """
    row = _select_period(load_data(), ticker, fiscal_year, fiscal_period)
    if row.empty:
        return {"error": f"No row found for {ticker} FY{fiscal_year} {fiscal_period}"}
    r = row.iloc[0]

    assets, liabilities, equity = r.total_assets, r.total_liabilities, r.stockholders_equity
    if pd.isna(assets) or pd.isna(liabilities) or pd.isna(equity):
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "status": "insufficient_data",
            "total_assets": None if pd.isna(assets) else assets,
            "total_liabilities": None if pd.isna(liabilities) else liabilities,
            "stockholders_equity": None if pd.isna(equity) else equity,
        }

    diff = assets - (liabilities + equity)
    pct_diff = abs(diff) / abs(assets) if assets != 0 else None

    return {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "total_assets": float(assets),
        "total_liabilities": float(liabilities),
        "stockholders_equity": float(equity),
        "difference": float(diff),
        "pct_difference": None if pct_diff is None else round(float(pct_diff), 4),
        "exceeds_1pct_tolerance": bool(pct_diff is not None and pct_diff > 0.01),
        "negative_equity": bool(equity < 0),
    }


def get_period_history(ticker: str, limit: int = 12) -> dict:
    """
    Return a ticker's recent period-over-period history for key metrics,
    so the agent can judge whether an anomaly is a one-off data error or
    part of a real, consistent pattern (e.g. a SPAC that always carries
    negative equity, or a biotech with genuinely lumpy revenue).
    """
    df = load_data()
    hist = df[df.ticker == ticker.upper()].sort_values("period_end_date")
    if hist.empty:
        return {"error": f"No data found for ticker {ticker}"}

    hist = hist.tail(limit)
    records = hist[
        [
            "fiscal_year", "fiscal_period", "form_type", "period_end_date",
            "revenues", "net_income", "total_assets", "total_liabilities",
            "stockholders_equity",
        ]
    ].copy()
    records["period_end_date"] = records["period_end_date"].dt.strftime("%Y-%m-%d")
    records = records.where(pd.notna(records), None)

    return {
        "ticker": ticker.upper(),
        "company_name": hist.iloc[-1].company_name,
        "periods_returned": len(records),
        "history": records.to_dict(orient="records"),
    }


def check_revenue_continuity(ticker: str, ratio_threshold: float = 20.0) -> dict:
    """
    Flag quarter-over-quarter revenue swings larger than `ratio_threshold`x
    (in either direction). A large swing is a candidate data/unit error,
    not a confirmed one -- real M&A, milestone payments, or a young
    biotech's first product revenue can all look like this.
    """
    df = load_data()
    hist = df[(df.ticker == ticker.upper()) & (df.form_type == "10-Q")]
    hist = hist.dropna(subset=["revenues"]).sort_values("period_end_date")
    if len(hist) < 2:
        return {"ticker": ticker.upper(), "flags": [], "note": "insufficient quarterly revenue history"}

    flags = []
    prev = None
    for _, r in hist.iterrows():
        if prev is not None and abs(prev.revenues) > 1000:
            ratio = r.revenues / prev.revenues if prev.revenues != 0 else None
            if ratio is not None and (ratio > ratio_threshold or ratio < 1 / ratio_threshold):
                flags.append({
                    "from_period": f"{int(prev.fiscal_year)}-{prev.fiscal_period}",
                    "to_period": f"{int(r.fiscal_year)}-{r.fiscal_period}",
                    "prev_revenue": float(prev.revenues),
                    "current_revenue": float(r.revenues),
                    "ratio": round(float(ratio), 4),
                })
        prev = r

    return {"ticker": ticker.upper(), "flags": flags}


def check_eps_consistency(ticker: str, fiscal_year: int, fiscal_period: str, tolerance: float = 0.50) -> dict:
    """
    Cross-check reported eps_basic against net_income / shares_outstanding.
    NOTE: basic EPS uses the *weighted average* shares outstanding during
    the period, not the period-end share count in this dataset -- so a
    mismatch here is expected in many legitimate cases (buybacks,
    issuances mid-quarter), not automatically an error. The agent must
    reason about this, not just flag every mismatch.
    """
    row = _select_period(load_data(), ticker, fiscal_year, fiscal_period)
    if row.empty:
        return {"error": f"No row found for {ticker} FY{fiscal_year} {fiscal_period}"}
    r = row.iloc[0]

    if pd.isna(r.eps_basic) or pd.isna(r.net_income) or pd.isna(r.shares_outstanding) or r.shares_outstanding == 0:
        return {
            "ticker": ticker, "fiscal_year": fiscal_year, "fiscal_period": fiscal_period,
            "status": "insufficient_data",
        }

    implied_eps = r.net_income / r.shares_outstanding
    diff = abs(implied_eps - r.eps_basic)

    return {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "reported_eps_basic": float(r.eps_basic),
        "implied_eps_from_net_income_and_shares": round(float(implied_eps), 4),
        "absolute_difference": round(float(diff), 4),
        "exceeds_tolerance": bool(diff > tolerance),
        "caveat": "shares_outstanding here is a period-end figure, not the weighted-average "
                  "figure basic EPS actually uses -- a mismatch is not automatically an error.",
    }


if __name__ == "__main__":
    # Quick self-test against known cases we already identified manually.
    import json

    print("=== check_balance_sheet: AACI Q2 2026 (known SPAC mismatch) ===")
    print(json.dumps(check_balance_sheet("AACI", 2026, "Q2"), indent=2))

    print("\n=== get_period_history: ABUS (known revenue scale-jump ticker) ===")
    print(json.dumps(get_period_history("ABUS", limit=6), indent=2))

    print("\n=== check_revenue_continuity: ABUS ===")
    print(json.dumps(check_revenue_continuity("ABUS"), indent=2))

    print("\n=== check_eps_consistency: sample lookup ===")
    df = load_data()
    sample = df.dropna(subset=["eps_basic", "net_income", "shares_outstanding"]).iloc[0]
    print(json.dumps(
        check_eps_consistency(sample.ticker, int(sample.fiscal_year), sample.fiscal_period),
        indent=2,
    ))
