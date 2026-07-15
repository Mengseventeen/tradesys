from datetime import datetime

from .local_data_common import (
    get_data_path,
    read_json_file,
    format_json_output,
)


ECONOMIC_INDICATORS = [
    "federal_funds_rate",
    "treasury_yield_3m",
    "treasury_yield_10y",
    "treasury_yield_30y",
    "cpi",
    "inflation",
    "unemployment",
    "nonfarm_payroll",
    "real_gdp",
    "retail_sales",
    "consumer_sentiment",
]


def _parse_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d")


def _rows_until_date(rows: list[dict], curr_date: str) -> list[dict]:
    """Return rows whose observation date is on or before curr_date."""
    curr_dt = _parse_date(curr_date)
    filtered = []

    for row in rows:
        try:
            row_dt = _parse_date(row["date"])
        except (KeyError, TypeError, ValueError):
            continue

        if row_dt <= curr_dt:
            filtered.append(row)

    return filtered


def _latest_row(data_type: str, curr_date: str) -> dict:
    data = read_json_file(get_data_path("economic_data") / f"{data_type}.json")
    rows = _rows_until_date(data.get("data", []), curr_date)
    return rows[-1] if rows else {}


def get_economic_data(
    data_type: str,
    curr_date: str,
    max_points: int | None = 30,
) -> str:
    """Get one economic series up to the analysis date."""
    file_path = get_data_path("economic_data") / f"{data_type}.json"
    data = read_json_file(file_path)

    rows = _rows_until_date(data.get("data", []), curr_date)
    matched_count = len(rows)

    if max_points is not None:
        rows = rows[-max_points:]

    return format_json_output({
        "data_type": data_type,
        "description": data.get("description", data_type),
        "series_id": data.get("series_id", ""),
        "curr_date": curr_date,
        "matched_count": matched_count,
        "returned_count": len(rows),
        "data": rows,
    })


def get_latest_economic_summary(curr_date: str) -> str:
    """Get the latest available value for each economic series by curr_date."""
    indicators = {}

    for data_type in ECONOMIC_INDICATORS:
        file_path = get_data_path("economic_data") / f"{data_type}.json"
        data = read_json_file(file_path)
        latest = _latest_row(data_type, curr_date)

        indicators[data_type] = {
            "description": data.get("description", data_type),
            "series_id": data.get("series_id", ""),
            "latest_date": latest.get("date"),
            "latest_value": latest.get("value"),
        }

    return format_json_output({
        "curr_date": curr_date,
        "indicators": indicators,
    })

def get_federal_funds_rate(curr_date: str, max_points: int | None = 30) -> str:
    return get_economic_data("federal_funds_rate", curr_date, max_points)


def get_treasury_yield(
    maturity: str,
    curr_date: str,
    max_points: int | None = 30,
) -> str:
    return get_economic_data(f"treasury_yield_{maturity}", curr_date, max_points)


def get_macro_summary(curr_date: str) -> str:
    return get_latest_economic_summary(curr_date)
