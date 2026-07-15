from datetime import datetime, timedelta

import pandas as pd

from .local_data_common import (
    DATA_ROOT,
    get_data_path,
    read_csv_file,
    format_json_output,
)


INDICATOR_DESCRIPTIONS = {
    "sma_50": "50-day simple moving average, used for medium-term trend direction.",
    "sma_200": "200-day simple moving average, used for long-term trend confirmation.",
    "ema_10": "10-day exponential moving average, used for short-term momentum.",
    "macd": "MACD line, used to evaluate trend momentum.",
    "macd_signal": "MACD signal line, used with MACD crossovers.",
    "macd_histogram": "MACD histogram, showing momentum acceleration or deceleration.",
    "rsi": "Relative Strength Index, used to identify overbought or oversold conditions.",
    "bollinger_middle": "Middle Bollinger Band.",
    "bollinger_upper": "Upper Bollinger Band.",
    "bollinger_lower": "Lower Bollinger Band.",
    "atr": "Average True Range, used to measure volatility.",
    "vwma": "Volume-weighted moving average.",
    "stoch_k": "Stochastic oscillator %K.",
    "stoch_d": "Stochastic oscillator %D.",
}


INDICATOR_ALIASES = {
    "close_50_sma": "sma_50",
    "50_sma": "sma_50",
    "sma50": "sma_50",
    "50ma": "sma_50",
    "sma": "sma_50",
    "close_200_sma": "sma_200",
    "200_sma": "sma_200",
    "sma200": "sma_200",
    "200ma": "sma_200",
    "close_10_ema": "ema_10",
    "10_ema": "ema_10",
    "ema10": "ema_10",
    "ema": "ema_10",
    "macds": "macd_signal",
    "macdh": "macd_histogram",
    "histogram": "macd_histogram",
    "relative_strength_index": "rsi",
    "boll": "bollinger_middle",
    "bollinger": "bollinger_middle",
    "bb": "bollinger_middle",
    "boll_ub": "bollinger_upper",
    "bb_upper": "bollinger_upper",
    "upper_band": "bollinger_upper",
    "boll_lb": "bollinger_lower",
    "bb_lower": "bollinger_lower",
    "lower_band": "bollinger_lower",
    "average_true_range": "atr",
    "volume": "vwma",
    "volume_weighted": "vwma",
    "stochastic": "stoch_k",
    "stoch": "stoch_k",
    "%k": "stoch_k",
    "%d": "stoch_d",
}


def list_available_stocks() -> str:
    """Return tickers that have local stock data."""
    stock_root = DATA_ROOT / "stock_data"
    tickers = []
    if stock_root.exists():
        tickers = sorted(
            path.name
            for path in stock_root.iterdir()
            if path.is_dir() and (path / "daily_prices.csv").exists()
        )

    return format_json_output({
        "tickers": tickers,
        "count": len(tickers),
    })


def list_available_indicators() -> str:
    """Return supported technical indicators and aliases."""
    return format_json_output({
        "indicators": INDICATOR_DESCRIPTIONS,
        "aliases": INDICATOR_ALIASES,
    })


def _parse_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d")


def _filter_frame_by_date(
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    date_column: str = "date",
) -> pd.DataFrame:
    out = df.copy()
    out[date_column] = pd.to_datetime(out[date_column])
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    return out[(out[date_column] >= start_dt) & (out[date_column] <= end_dt)]


def _normalize_indicator(indicator: str) -> str:
    normalized = INDICATOR_ALIASES.get(indicator.lower(), indicator.lower())
    if normalized not in INDICATOR_DESCRIPTIONS:
        supported = sorted(INDICATOR_DESCRIPTIONS)
        raise ValueError(f"Unsupported indicator: {indicator}. Supported indicators: {supported}")
    return normalized


def get_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
    max_rows: int | None = 30,
) -> str:
    """Return OHLCV rows for symbol within the requested date range."""
    file_path = get_data_path("stock_data", symbol) / "daily_prices.csv"
    df = read_csv_file(file_path)
    df_filtered = _filter_frame_by_date(df, start_date, end_date)
    df_filtered = df_filtered.sort_values("date", ascending=False)

    matched_count = len(df_filtered)
    if max_rows is not None:
        df_filtered = df_filtered.head(max_rows)

    df_filtered = df_filtered.copy()
    df_filtered["date"] = df_filtered["date"].dt.strftime("%Y-%m-%d")

    return format_json_output({
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "matched_count": matched_count,
        "returned_count": len(df_filtered),
        "data": df_filtered.to_dict(orient="records"),
    })


def get_indicator_data(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 15,
    max_rows: int | None = 15,
) -> str:
    """Return one technical indicator up to curr_date."""
    normalized = _normalize_indicator(indicator)
    curr_dt = _parse_date(curr_date)
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    file_path = get_data_path("stock_data", symbol) / "technical_indicators.csv"
    df = read_csv_file(file_path)
    df_filtered = _filter_frame_by_date(df, start_date, curr_date)
    df_filtered = df_filtered.sort_values("date", ascending=False)

    matched_count = len(df_filtered)
    if max_rows is not None:
        df_filtered = df_filtered.head(max_rows)

    rows = []
    for _, row in df_filtered.iterrows():
        date_value = row["date"]
        rows.append({
            "date": date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else str(date_value),
            "value": None if pd.isna(row.get(normalized)) else row.get(normalized),
        })

    return format_json_output({
        "symbol": symbol,
        "indicator": normalized,
        "curr_date": curr_date,
        "look_back_days": look_back_days,
        "description": INDICATOR_DESCRIPTIONS[normalized],
        "matched_count": matched_count,
        "returned_count": len(rows),
        "data": rows,
    })


def get_indicators_data(
    symbol: str,
    indicators: list[str],
    curr_date: str,
    look_back_days: int = 15,
    max_rows: int | None = 15,
) -> str:
    """Return multiple technical indicators up to curr_date."""
    normalized_indicators = []
    for indicator in indicators:
        normalized = _normalize_indicator(indicator)
        if normalized not in normalized_indicators:
            normalized_indicators.append(normalized)

    curr_dt = _parse_date(curr_date)
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    file_path = get_data_path("stock_data", symbol) / "technical_indicators.csv"
    df = read_csv_file(file_path)
    df_filtered = _filter_frame_by_date(df, start_date, curr_date)
    df_filtered = df_filtered.sort_values("date", ascending=False)

    matched_count = len(df_filtered)
    if max_rows is not None:
        df_filtered = df_filtered.head(max_rows)

    rows = []
    for _, row in df_filtered.iterrows():
        date_value = row["date"]
        item = {
            "date": date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else str(date_value),
        }
        for indicator in normalized_indicators:
            value = row.get(indicator)
            item[indicator] = None if pd.isna(value) else value
        rows.append(item)

    return format_json_output({
        "symbol": symbol,
        "indicators": normalized_indicators,
        "curr_date": curr_date,
        "look_back_days": look_back_days,
        "descriptions": {
            indicator: INDICATOR_DESCRIPTIONS[indicator]
            for indicator in normalized_indicators
        },
        "matched_count": matched_count,
        "returned_count": len(rows),
        "data": rows,
    })


def get_indicator_on_date(symbol: str, indicator: str, trade_date: str) -> str:
    """Return one technical indicator for one symbol on one exact date."""
    normalized = _normalize_indicator(indicator)
    file_path = get_data_path("stock_data", symbol) / "technical_indicators.csv"
    df = read_csv_file(file_path)
    df_filtered = _filter_frame_by_date(df, trade_date, trade_date)

    if df_filtered.empty:
        return format_json_output({
            "symbol": symbol,
            "indicator": normalized,
            "trade_date": trade_date,
            "description": INDICATOR_DESCRIPTIONS[normalized],
            "found": False,
            "value": None,
        })

    row = df_filtered.sort_values("date", ascending=False).iloc[0]
    value = row.get(normalized)

    return format_json_output({
        "symbol": symbol,
        "indicator": normalized,
        "trade_date": trade_date,
        "description": INDICATOR_DESCRIPTIONS[normalized],
        "found": True,
        "value": None if pd.isna(value) else value,
    })
