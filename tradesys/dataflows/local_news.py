import json
from datetime import datetime, timedelta
from .local_data_common import (
    get_data_path,
    read_json_file,
    format_json_output,
)

def get_news_data(ticker: str, start_date: str, end_date: str) -> str:
    file_path = get_data_path("news_data") / f"{ticker}_news.json"
    data = read_json_file(file_path)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    filtered = []
    for article in data.get("feed", []):
        try:
            article_dt = datetime.strptime(article["time_published"], "%Y%m%dT%H%M%S")
        except (KeyError, ValueError):
            continue

        if start_dt <= article_dt < end_dt:
            filtered.append(article)

    filtered.sort(key=lambda x: x.get("time_published", ""), reverse=True)

    return format_json_output({
        "feed": filtered[:500]
    })


def get_news_on_date(ticker: str, trade_date: str, limit: int | None = 500) -> str:
    """Return news for one ticker on one analysis date."""
    file_path = get_data_path("news_data") / f"{ticker}_news.json"
    data = read_json_file(file_path)

    day_start = datetime.strptime(trade_date, "%Y-%m-%d")
    day_end = day_start + timedelta(days=1)

    filtered = []
    for article in data.get("feed", []):
        try:
            article_dt = datetime.strptime(article["time_published"], "%Y%m%dT%H%M%S")
        except (KeyError, ValueError):
            continue

        if day_start <= article_dt < day_end:
            filtered.append(article)

    filtered.sort(key=lambda x: x.get("time_published", ""), reverse=True)

    if limit is None:
        returned = filtered
    else:
        returned = filtered[:limit]

    return format_json_output({
        "ticker": ticker,
        "trade_date": trade_date,
        "matched_count": len(filtered),
        "returned_count": len(returned),
        "limit": limit,
        "feed": returned,
    })
