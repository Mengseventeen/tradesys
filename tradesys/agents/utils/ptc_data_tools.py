from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Callable

from langchain_core.tools import tool

from tradesys.dataflows.local_economic import (
    get_economic_data,
    get_latest_economic_summary,
)
from tradesys.dataflows.local_fundamentals import (
    get_earnings_data,
    get_filings_data,
    get_latest_fundamental_summary,
)
from tradesys.dataflows.local_news import get_news_data
from tradesys.dataflows.local_stock import get_indicators_data, get_stock_data


def _load(payload: str) -> dict[str, Any]:
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def _run_program(
    program_name: str,
    calls: list[tuple[str, Callable[[], str]]],
) -> str:
    """Execute a fixed, read-only PTC program and retain a compact call trace."""
    outputs: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    for name, function in calls:
        raw = function()
        parsed = _load(raw)
        outputs[name] = parsed
        trace.append({
            "tool": name,
            "output_keys": sorted(parsed),
            "serialized_chars": len(raw),
        })
    return json.dumps(
        {
            "ptc_program": program_name,
            "tool_call_count": len(calls),
            "call_trace": trace,
            "outputs": outputs,
        },
        ensure_ascii=False,
    )


@tool
def collect_technical_evidence_ptc(
    ticker: Annotated[str, "Ticker symbol"],
    trade_date: Annotated[str, "Analysis cutoff in YYYY-MM-DD format"],
) -> str:
    """Run one read-only program that collects prices and all relevant technical indicators."""
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - timedelta(days=120)).strftime("%Y-%m-%d")
    indicators = [
        "rsi",
        "stoch_k",
        "stoch_d",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr",
    ]
    return _run_program(
        "technical_evidence_v1",
        [
            ("prices", lambda: get_stock_data(ticker, start, trade_date, max_rows=80)),
            (
                "indicators",
                lambda: get_indicators_data(
                    ticker,
                    indicators,
                    trade_date,
                    look_back_days=120,
                    max_rows=40,
                ),
            ),
        ],
    )


@tool
def collect_fundamental_evidence_ptc(
    ticker: Annotated[str, "Ticker symbol"],
    trade_date: Annotated[str, "Analysis cutoff in YYYY-MM-DD format"],
) -> str:
    """Run one read-only program that joins statements, earnings, and the latest filing."""
    return _run_program(
        "fundamental_evidence_v1",
        [
            (
                "statement_summary",
                lambda: get_latest_fundamental_summary(ticker, trade_date, "quarterly", compact=True),
            ),
            ("earnings", lambda: get_earnings_data(ticker, trade_date, max_reports=4)),
            (
                "filings",
                lambda: get_filings_data(
                    ticker,
                    trade_date,
                    max_filings=1,
                    max_chars_per_filing=5000,
                ),
            ),
        ],
    )


@tool
def collect_news_evidence_ptc(
    ticker: Annotated[str, "Ticker symbol"],
    trade_date: Annotated[str, "Analysis cutoff in YYYY-MM-DD format"],
) -> str:
    """Run one read-only program that collects, deduplicates, and compacts recent news."""
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - timedelta(days=7)).strftime("%Y-%m-%d")
    payload = _load(get_news_data(ticker, start, trade_date))
    seen: set[str] = set()
    articles: list[dict[str, Any]] = []
    for article in payload.get("feed", []):
        title = str(article.get("title", "")).strip()
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        articles.append({
            "time_published": article.get("time_published"),
            "title": title[:240],
            "summary": str(article.get("summary", ""))[:700],
            "overall_sentiment_score": article.get("overall_sentiment_score"),
            "overall_sentiment_label": article.get("overall_sentiment_label"),
        })
        if len(articles) >= 15:
            break
    return json.dumps(
        {
            "ptc_program": "news_evidence_v1",
            "tool_call_count": 1,
            "call_trace": [{"tool": "get_news_data", "matched": len(payload.get("feed", []))}],
            "outputs": {
                "ticker": ticker,
                "start_date": start,
                "trade_date": trade_date,
                "returned_count": len(articles),
                "articles": articles,
            },
        },
        ensure_ascii=False,
    )


@tool
def collect_policy_evidence_ptc(
    trade_date: Annotated[str, "Analysis cutoff in YYYY-MM-DD format"],
) -> str:
    """Run one read-only program that joins the macro snapshot with recent rate and inflation history."""
    series = [
        "federal_funds_rate",
        "treasury_yield_3m",
        "treasury_yield_10y",
        "inflation",
        "unemployment",
        "consumer_sentiment",
    ]
    calls: list[tuple[str, Callable[[], str]]] = [
        ("latest_summary", lambda: get_latest_economic_summary(trade_date))
    ]
    calls.extend(
        (
            name,
            lambda name=name: get_economic_data(name, trade_date, max_points=12),
        )
        for name in series
    )
    return _run_program("policy_evidence_v1", calls)
