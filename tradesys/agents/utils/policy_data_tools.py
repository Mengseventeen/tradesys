from typing import Annotated

from langchain_core.tools import tool

from tradesys.dataflows.local_economic import (
    get_economic_data as _get_economic_data,
    get_federal_funds_rate as _get_federal_funds_rate,
    get_latest_economic_summary as _get_latest_economic_summary,
    get_macro_summary as _get_macro_summary,
    get_treasury_yield as _get_treasury_yield,
)


@tool
def get_economic_data(
    data_type: Annotated[str, "Economic series name, for example federal_funds_rate or cpi"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    max_points: Annotated[int, "Maximum observations to return"] = 30,
) -> str:
    """Return one economic series up to the analysis date."""
    return _get_economic_data(data_type, curr_date, max_points)


@tool
def get_macro_summary(
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
) -> str:
    """Return the latest available value for each macroeconomic series."""
    return _get_macro_summary(curr_date)


@tool
def get_federal_funds_rate(
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    max_points: Annotated[int, "Maximum observations to return"] = 30,
) -> str:
    """Return federal funds rate observations up to the analysis date."""
    return _get_federal_funds_rate(curr_date, max_points)


@tool
def get_treasury_yield(
    maturity: Annotated[str, "Treasury maturity, for example 3m, 10y, or 30y"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    max_points: Annotated[int, "Maximum observations to return"] = 30,
) -> str:
    """Return Treasury yield observations up to the analysis date."""
    return _get_treasury_yield(maturity, curr_date, max_points)


@tool
def get_latest_economic_summary(
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
) -> str:
    """Return the latest available value for each economic indicator."""
    return _get_latest_economic_summary(curr_date)
