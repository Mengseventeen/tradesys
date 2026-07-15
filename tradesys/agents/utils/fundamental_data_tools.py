from typing import Annotated

from langchain_core.tools import tool

from tradesys.dataflows.local_fundamentals import (
    get_balance_sheet_data as _get_balance_sheet_data,
    get_cashflow_data as _get_cashflow_data,
    get_earnings_data as _get_earnings_data,
    get_filings_data as _get_filings_data,
    get_income_statement_data as _get_income_statement_data,
    get_latest_fundamental_summary as _get_latest_fundamental_summary,
    get_statement_data as _get_statement_data,
)


@tool
def get_statement_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    statement_type: Annotated[str, "One of: balance_sheet, cashflow, income_statement"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    freq: Annotated[str, "Report frequency: quarterly or annual"] = "quarterly",
    max_reports: Annotated[int, "Maximum reports to return"] = 5,
    compact: Annotated[bool, "Whether to return only key fields and parsed numeric values"] = False,
) -> str:
    """Return recent rows from one financial statement."""
    return _get_statement_data(ticker, statement_type, curr_date, freq, max_reports, compact)


@tool
def get_balance_sheet_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    freq: Annotated[str, "Report frequency: quarterly or annual"] = "quarterly",
    max_reports: Annotated[int, "Maximum reports to return"] = 5,
    compact: Annotated[bool, "Whether to return only key fields and parsed numeric values"] = False,
) -> str:
    """Return recent balance sheet rows."""
    return _get_balance_sheet_data(ticker, curr_date, freq, max_reports, compact)


@tool
def get_cashflow_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    freq: Annotated[str, "Report frequency: quarterly or annual"] = "quarterly",
    max_reports: Annotated[int, "Maximum reports to return"] = 5,
    compact: Annotated[bool, "Whether to return only key fields and parsed numeric values"] = False,
) -> str:
    """Return recent cash flow statement rows."""
    return _get_cashflow_data(ticker, curr_date, freq, max_reports, compact)


@tool
def get_income_statement_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    freq: Annotated[str, "Report frequency: quarterly or annual"] = "quarterly",
    max_reports: Annotated[int, "Maximum reports to return"] = 5,
    compact: Annotated[bool, "Whether to return only key fields and parsed numeric values"] = False,
) -> str:
    """Return recent income statement rows."""
    return _get_income_statement_data(ticker, curr_date, freq, max_reports, compact)


@tool
def get_latest_fundamental_summary(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    freq: Annotated[str, "Report frequency: quarterly or annual"] = "quarterly",
    compact: Annotated[bool, "Whether to return only key fields and parsed numeric values"] = True,
) -> str:
    """Return the latest available row from each financial statement."""
    return _get_latest_fundamental_summary(ticker, curr_date, freq, compact)


@tool
def get_earnings_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    max_reports: Annotated[int, "Maximum quarterly and annual earnings rows to return"] = 5,
) -> str:
    """Return recent earnings rows in the same shape as earnings.json."""
    return _get_earnings_data(ticker, curr_date, max_reports)


@tool
def get_filings_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    max_filings: Annotated[int, "Maximum filings to return"] = 1,
    max_chars_per_filing: Annotated[int, "Maximum characters to return per filing"] = 4000,
) -> str:
    """Return recent 10-Q or 10-K filing text."""
    return _get_filings_data(ticker, curr_date, max_filings, max_chars_per_filing)
