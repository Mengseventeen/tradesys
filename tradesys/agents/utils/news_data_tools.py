from typing import Annotated

from langchain_core.tools import tool

from tradesys.dataflows.local_news import (
    get_news_data as _get_news_data,
    get_news_on_date as _get_news_on_date,
)


@tool
def get_news_data(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    start_date: Annotated[str, "Start date in YYYY-MM-DD format"],
    end_date: Annotated[str, "End date in YYYY-MM-DD format"],
) -> str:
    """Return ticker news in a date range."""
    return _get_news_data(ticker, start_date, end_date)


@tool
def get_news_on_date(
    ticker: Annotated[str, "Ticker symbol, for example AMZN, MSFT, NFLX, or TSLA"],
    trade_date: Annotated[str, "Exact analysis date in YYYY-MM-DD format"],
    limit: Annotated[int, "Maximum articles to return"] = 500,
) -> str:
    """Return ticker news on one exact analysis date."""
    return _get_news_on_date(ticker, trade_date, limit)
