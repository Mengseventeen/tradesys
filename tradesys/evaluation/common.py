from __future__ import annotations

import csv
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_TICKERS = ["TSLA", "NFLX", "AMZN", "MSFT"]
INITIAL_CASH = 100000.0
RISK_FREE_RATE = 0.03
COMMISSION_PER_SHARE = 0.0049
MIN_COMMISSION = 0.99
MAX_COMMISSION_RATE = 0.01
TRADING_DAYS_PER_YEAR = 252

BUY_ACTIONS = {"BUY", "LONG", "1"}
SELL_ACTIONS = {"SELL", "SHORT", "EXIT", "CLOSE", "-1"}
HOLD_ACTIONS = {"HOLD", "WATCH", "AVOID", "REVIEW_ONLY", "0", ""}


def parse_date(value: Any) -> date:
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip().replace("%", "").replace(",", ""))
    except ValueError:
        return default


def normalize_action(value: Any, position_pct: float = 0.0) -> str:
    action = str(value or "").strip().upper()
    if action in BUY_ACTIONS:
        return "BUY"
    if action in SELL_ACTIONS:
        return "SELL"
    if action in HOLD_ACTIONS:
        return "HOLD"
    if position_pct > 0:
        return "BUY"
    if position_pct < 0:
        return "SELL"
    return "HOLD"


def get_column(row: dict[str, Any], names: tuple[str, ...], default: str = "") -> str:
    lowered = {key.lower(): key for key in row}
    for name in names:
        key = lowered.get(name.lower())
        if key is not None:
            return str(row.get(key, default))
    return default


def calculate_commission(
    quantity: int,
    price: float,
    commission_per_share: float = COMMISSION_PER_SHARE,
    min_commission: float = MIN_COMMISSION,
    max_commission_rate: float = MAX_COMMISSION_RATE,
) -> float:
    if quantity <= 0 or price <= 0:
        return 0.0
    commission = abs(quantity) * commission_per_share
    transaction_amount = abs(quantity * price)
    return max(min_commission, min(commission, transaction_amount * max_commission_rate))


def adjust_size_for_budget(
    budget: float,
    price: float,
    commission_per_share: float = COMMISSION_PER_SHARE,
    min_commission: float = MIN_COMMISSION,
    max_commission_rate: float = MAX_COMMISSION_RATE,
) -> int:
    if budget <= 0 or price <= 1e-8:
        return 0

    quantity = int(budget / price)
    while quantity > 0:
        commission = calculate_commission(
            quantity,
            price,
            commission_per_share,
            min_commission,
            max_commission_rate,
        )
        if budget >= quantity * price + commission:
            return quantity
        next_quantity = int((budget - commission) / price)
        quantity = next_quantity if next_quantity < quantity else quantity - 1

    return 0


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def daily_returns(equity: list[dict[str, Any]]) -> list[float]:
    values = [row["equity"] for row in equity]
    return [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
    ]


def maximum_drawdown_pct(equity: list[dict[str, Any]]) -> float:
    peak = equity[0]["equity"]
    worst = 0.0
    for row in equity:
        peak = max(peak, row["equity"])
        worst = min(worst, row["equity"] / peak - 1.0)
    return worst * 100.0


def fill_calendar_days(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date = {bar["date"]: bar for bar in bars}
    current = bars[0]["date"]
    end = bars[-1]["date"]
    last_bar = bars[0]
    filled = []

    while current <= end:
        if current in by_date:
            last_bar = by_date[current]
        filled.append({
            "date": current,
            "open": last_bar["open"],
            "high": last_bar["high"],
            "low": last_bar["low"],
            "close": last_bar["close"],
        })
        current += timedelta(days=1)

    return filled


def load_adjusted_bars(
    prices_root: Path,
    ticker: str,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    csv_path = prices_root / ticker / "daily_prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Daily price file not found: {csv_path}")

    start = parse_date(date_from)
    end = parse_date(date_to)
    bars: list[dict[str, Any]] = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"date", "open", "high", "low", "close", "adjusted_close"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            current_date = parse_date(row["date"])
            if current_date < start or current_date >= end:
                continue

            close = parse_float(row["close"], math.nan)
            adjusted_close = parse_float(row["adjusted_close"], math.nan)
            if math.isnan(close) or math.isnan(adjusted_close) or close <= 0 or adjusted_close <= 0:
                continue

            factor = adjusted_close / close
            bars.append({
                "date": current_date,
                "open": parse_float(row["open"], math.nan) * factor,
                "high": parse_float(row["high"], math.nan) * factor,
                "low": parse_float(row["low"], math.nan) * factor,
                "close": adjusted_close,
            })

    if not bars:
        raise ValueError(f"No price rows found for {ticker} in [{date_from}, {date_to})")

    return fill_calendar_days(sorted(bars, key=lambda item: item["date"]))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fieldnames} for row in rows)
