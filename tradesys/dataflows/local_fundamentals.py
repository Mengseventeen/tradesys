from datetime import datetime

from .local_data_common import (
    get_data_path,
    read_json_file,
    format_json_output,
)


FUNDAMENTAL_STATEMENTS = {
    "balance_sheet": "balance_sheet.json",
    "cashflow": "cashflow.json",
    "income_statement": "income_statement.json",
}

COMPACT_STATEMENT_FIELDS = {
    "income_statement": [
        "fiscalDateEnding",
        "reportedCurrency",
        "totalRevenue",
        "grossProfit",
        "operatingIncome",
        "netIncome",
        "ebit",
        "ebitda",
        "researchAndDevelopment",
        "sellingGeneralAndAdministrative",
        "costOfRevenue",
        "incomeTaxExpense",
        "interestExpense",
        "depreciationAndAmortization",
    ],
    "balance_sheet": [
        "fiscalDateEnding",
        "reportedCurrency",
        "totalAssets",
        "totalLiabilities",
        "totalCurrentAssets",
        "totalCurrentLiabilities",
        "cashAndCashEquivalentsAtCarryingValue",
        "inventory",
        "currentNetReceivables",
        "propertyPlantEquipment",
        "goodwill",
        "intangibleAssets",
        "currentAccountsPayable",
        "shortTermDebt",
        "longTermDebt",
        "totalShareholderEquity",
    ],
    "cashflow": [
        "fiscalDateEnding",
        "reportedCurrency",
        "operatingCashflow",
        "capitalExpenditures",
        "cashflowFromInvestment",
        "cashflowFromFinancing",
        "depreciationDepletionAndAmortization",
        "changeInReceivables",
        "changeInInventory",
        "stockBasedCompensation",
        "netIncome",
    ],
}


def _parse_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d")


def _rows_until_date(rows: list[dict], curr_date: str, date_key: str) -> list[dict]:
    curr_dt = _parse_date(curr_date)
    filtered = []

    for row in rows:
        try:
            row_dt = _parse_date(row[date_key])
        except (KeyError, TypeError, ValueError):
            continue

        if row_dt <= curr_dt:
            filtered.append(row)

    return sorted(filtered, key=lambda row: row[date_key], reverse=True)


def _parse_value(value):
    if value in (None, "None", ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _normalize_row(row: dict, fields: list[str] | None = None) -> dict:
    source = row if fields is None else {field: row.get(field) for field in fields}
    return {
        key: _parse_value(value)
        for key, value in source.items()
    }


def _report_key(freq: str) -> str:
    if freq not in ("quarterly", "annual"):
        raise ValueError("freq must be 'quarterly' or 'annual'")
    return "quarterlyReports" if freq == "quarterly" else "annualReports"


def _positive_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    return max(1, int(limit))


def _limit_rows(rows: list[dict], limit: int | None) -> list[dict]:
    limit = _positive_limit(limit)
    if limit is None:
        return rows
    return rows[:limit]


def _read_statement_rows(
    ticker: str,
    statement_type: str,
    curr_date: str,
    freq: str,
    compact: bool = False,
) -> list[dict]:
    if statement_type not in FUNDAMENTAL_STATEMENTS:
        valid = ", ".join(FUNDAMENTAL_STATEMENTS)
        raise ValueError(f"statement_type must be one of: {valid}")

    file_path = get_data_path("stock_data", ticker) / FUNDAMENTAL_STATEMENTS[statement_type]
    data = read_json_file(file_path)
    rows = _rows_until_date(data.get(_report_key(freq), []), curr_date, "fiscalDateEnding")
    fields = COMPACT_STATEMENT_FIELDS[statement_type] if compact else None
    return [_normalize_row(row, fields) for row in rows]


def get_statement_data(
    ticker: str,
    statement_type: str,
    curr_date: str,
    freq: str = "quarterly",
    max_reports: int | None = 5,
    compact: bool = False,
) -> str:
    """Return recent balance sheet, cashflow, or income statement rows."""
    rows = _read_statement_rows(ticker, statement_type, curr_date, freq, compact)
    returned = _limit_rows(rows, max_reports)

    return format_json_output({
        "ticker": ticker,
        "curr_date": curr_date,
        "statement_type": statement_type,
        "frequency": freq,
        "compact": compact,
        "matched_count": len(rows),
        "returned_count": len(returned),
        "data": returned,
    })


def get_balance_sheet_data(
    ticker: str,
    curr_date: str,
    freq: str = "quarterly",
    max_reports: int | None = 5,
    compact: bool = False,
) -> str:
    return get_statement_data(ticker, "balance_sheet", curr_date, freq, max_reports, compact)


def get_cashflow_data(
    ticker: str,
    curr_date: str,
    freq: str = "quarterly",
    max_reports: int | None = 5,
    compact: bool = False,
) -> str:
    return get_statement_data(ticker, "cashflow", curr_date, freq, max_reports, compact)


def get_income_statement_data(
    ticker: str,
    curr_date: str,
    freq: str = "quarterly",
    max_reports: int | None = 5,
    compact: bool = False,
) -> str:
    return get_statement_data(ticker, "income_statement", curr_date, freq, max_reports, compact)


def get_latest_fundamental_summary(
    ticker: str,
    curr_date: str,
    freq: str = "quarterly",
    compact: bool = True,
) -> str:
    """Return the latest available row from each financial statement."""
    summary = {}

    for statement_type in FUNDAMENTAL_STATEMENTS:
        rows = _read_statement_rows(ticker, statement_type, curr_date, freq, compact)
        summary[statement_type] = rows[0] if rows else {}

    return format_json_output({
        "ticker": ticker,
        "curr_date": curr_date,
        "frequency": freq,
        "compact": compact,
        "statements": summary,
    })


def get_earnings_data(
    ticker: str,
    curr_date: str,
    max_reports: int | None = 5,
) -> str:
    """Return recent earnings rows in the same shape as earnings.json."""
    file_path = get_data_path("stock_data", ticker) / "earnings.json"
    data = read_json_file(file_path)

    quarterly = _rows_until_date(data.get("quarterlyEarnings", []), curr_date, "fiscalDateEnding")
    annual = _rows_until_date(data.get("annualEarnings", []), curr_date, "fiscalDateEnding")
    quarterly = [_normalize_row(row) for row in quarterly]
    annual = [_normalize_row(row) for row in annual]
    returned_quarterly = _limit_rows(quarterly, max_reports)
    returned_annual = _limit_rows(annual, max_reports)

    return format_json_output({
        "ticker": ticker,
        "curr_date": curr_date,
        "quarterly_matched_count": len(quarterly),
        "quarterly_returned_count": len(returned_quarterly),
        "annual_matched_count": len(annual),
        "annual_returned_count": len(returned_annual),
        "quarterlyEarnings": returned_quarterly,
        "annualEarnings": returned_annual,
    })


def get_filings_data(
    ticker: str,
    curr_date: str,
    max_filings: int | None = 1,
    max_chars_per_filing: int | None = 4000,
) -> str:
    """Return recent 10-Q or 10-K filing text."""
    filings_dir = get_data_path("stock_data", ticker) / "filings"
    index = read_json_file(filings_dir / "index.json")
    rows = _rows_until_date(index.get("quarterly", []) + index.get("annual", []), curr_date, "date")

    filings = []
    for item in _limit_rows(rows, max_filings):
        file_path = filings_dir / item["file"]
        text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        full_length = len(text)

        if max_chars_per_filing is not None:
            text = text[:max_chars_per_filing]

        filings.append({
            "date": item.get("date"),
            "file": item.get("file"),
            "full_length": full_length,
            "returned_length": len(text),
            "text": text,
        })

    return format_json_output({
        "ticker": ticker,
        "curr_date": curr_date,
        "matched_count": len(rows),
        "returned_count": len(filings),
        "filings": filings,
    })
