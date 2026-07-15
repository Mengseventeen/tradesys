from typing import Annotated

from langchain_core.tools import tool

from tradesys.dataflows.local_stock import (
    list_available_stocks as _list_available_stocks,
    list_available_indicators as _list_available_indicators,
    get_stock_data as _get_stock_data,
    get_indicator_data as _get_indicator_data,
    get_indicators_data as _get_indicators_data,
    get_indicator_on_date as _get_indicator_on_date,
)


@tool
def list_available_stocks() -> str:
    """Return ticker symbols available in the local stock data."""
    return _list_available_stocks()


@tool
def list_available_indicators() -> str:
    """Return supported technical indicators and aliases."""
    return _list_available_indicators()


@tool
def get_stock_data(
    symbol: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    start_date: Annotated[str, "Start date in YYYY-MM-DD format"],
    end_date: Annotated[str, "End date in YYYY-MM-DD format"],
    max_rows: Annotated[int, "Maximum rows to return"] = 30,
) -> str:
    """Return OHLCV price rows for one ticker in a date range."""
    return _get_stock_data(symbol, start_date, end_date, max_rows)


@tool
def get_indicator_data(
    symbol: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    indicator: Annotated[str, "Indicator name, for example rsi, macd, sma_50, sma_200"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "Number of calendar days to look back"] = 15,
    max_rows: Annotated[int, "Maximum rows to return"] = 15,
) -> str:
    """Return one technical indicator up to the analysis date."""
    return _get_indicator_data(symbol, indicator, curr_date, look_back_days, max_rows)


@tool
def get_indicators_data(
    symbol: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    indicators: Annotated[list[str], "Indicator names, for example ['rsi', 'macd', 'sma_50']"],
    curr_date: Annotated[str, "Analysis date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "Number of calendar days to look back"] = 15,
    max_rows: Annotated[int, "Maximum rows to return"] = 15,
) -> str:
    """Return multiple technical indicators up to the analysis date."""
    return _get_indicators_data(symbol, indicators, curr_date, look_back_days, max_rows)


@tool
def get_indicator_on_date(
    symbol: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    indicator: Annotated[str, "Indicator name, for example rsi, macd, sma_50, sma_200"],
    trade_date: Annotated[str, "Exact trading date in YYYY-MM-DD format"],
) -> str:
    """Return one technical indicator value on one exact trading date."""
    return _get_indicator_on_date(symbol, indicator, trade_date)
