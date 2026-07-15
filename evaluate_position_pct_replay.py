import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


EXERCISE_ROOT = Path(__file__).parent
DEFAULT_PRICES_ROOT = EXERCISE_ROOT / "tradesys" / "data_portfolio" / "stock_data"

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


def pct_to_fraction(value: Any) -> float:
    return min(1.0, max(0.0, abs(parse_float(value, 0.0)) / 100.0))


def normalize_action(value: Any, position_pct: float) -> str:
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


def calculate_commission(size: int, price: float) -> float:
    transaction_amount = abs(size * price)
    raw_commission = abs(size) * COMMISSION_PER_SHARE
    return min(max(raw_commission, MIN_COMMISSION), transaction_amount * MAX_COMMISSION_RATE)


def adjust_size_for_budget(budget: float, price: float) -> int:
    if budget <= 0 or price <= 1e-8:
        return 0

    max_size = int(budget / price)
    while max_size > 0:
        commission = calculate_commission(max_size, price)
        if budget >= max_size * price + commission:
            return max_size
        next_size = int((budget - commission) / price)
        max_size = next_size if next_size < max_size else max_size - 1

    return 0


def load_decisions(path: Path, include_errors: bool = False) -> dict[str, dict[date, dict[str, Any]]]:
    decisions: dict[str, dict[date, dict[str, Any]]] = defaultdict(dict)

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Decision file has no header: {path}")

        fields = {field.lower() for field in reader.fieldnames}
        if "ticker" not in fields and "symbol" not in fields:
            raise ValueError("Decision file is missing required column: ticker/symbol")
        if not ({"trade_date", "date", "datetime"} & fields):
            raise ValueError("Decision file is missing required column: trade_date/date/datetime")

        for row in reader:
            status = get_column(row, ("status",), "ok").strip().lower()
            if not include_errors and status and status != "ok":
                continue

            ticker = get_column(row, ("ticker", "symbol")).strip().upper()
            raw_date = get_column(row, ("trade_date", "date", "datetime")).strip()
            if not ticker or not raw_date:
                continue

            raw_pct = get_column(row, ("position_pct", "position_pcct", "position_size", "position"), "0")
            position_pct = parse_float(raw_pct, 0.0)
            action = normalize_action(get_column(row, ("action", "decision", "signal")), position_pct)

            decisions[ticker][parse_date(raw_date)] = {
                "action": action,
                "raw_action": get_column(row, ("action", "decision", "signal")),
                "position_pct": position_pct,
                "position_fraction": pct_to_fraction(raw_pct),
                "status": status or "ok",
            }

    return dict(decisions)


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
                "open": parse_float(row["open"]) * factor,
                "high": parse_float(row["high"]) * factor,
                "low": parse_float(row["low"]) * factor,
                "close": adjusted_close,
            })

    if not bars:
        raise ValueError(f"No price rows found for {ticker} in [{date_from}, {date_to})")

    return fill_calendar_days(sorted(bars, key=lambda item: item["date"]))


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


def default_date_window(decisions: dict[str, dict[date, dict[str, Any]]]) -> tuple[str, str]:
    all_dates = [current_date for ticker_decisions in decisions.values() for current_date in ticker_decisions]
    start = min(all_dates)
    end_exclusive = max(all_dates) + timedelta(days=1)
    return start.isoformat(), end_exclusive.isoformat()


def execute_buy(cash: float, price: float, fraction: float) -> tuple[int, float, float]:
    budget = cash * fraction
    shares = adjust_size_for_budget(budget, price)
    if shares <= 0:
        return 0, 0.0, cash

    commission = calculate_commission(shares, price)
    total_cost = shares * price + commission
    if total_cost > cash:
        return 0, 0.0, cash
    return shares, commission, cash - total_cost


def execute_sell(current_shares: int, price: float, fraction: float) -> tuple[int, float, float]:
    shares_to_sell = current_shares if fraction >= 1.0 else int(current_shares * fraction)
    if shares_to_sell <= 0:
        return 0, 0.0, 0.0

    commission = calculate_commission(shares_to_sell, price)
    revenue = shares_to_sell * price - commission
    return shares_to_sell, commission, revenue


def replay_decisions(
    ticker: str,
    decisions: dict[date, dict[str, Any]],
    bars: list[dict[str, Any]],
    initial_cash: float,
    execution: str,
    final_liquidation: bool,
) -> dict[str, Any]:
    cash = initial_cash
    shares = 0
    pending_order: dict[str, Any] | None = None
    equity: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for bar in bars:
        current_date = bar["date"]
        decision = decisions.get(current_date)
        executed_action = "HOLD"
        trade_quantity = 0
        commission = 0.0
        trade_price = ""

        if execution == "next_day_open" and pending_order:
            action = pending_order["action"]
            trade_price = bar["open"]
            if action == "BUY":
                trade_quantity = pending_order["quantity"]
                commission = calculate_commission(trade_quantity, trade_price)
                total_cost = trade_quantity * trade_price + commission
                if trade_quantity > 0 and cash >= total_cost:
                    cash -= total_cost
                    shares += trade_quantity
                    executed_action = "BUY"
            elif action == "SELL":
                trade_quantity = min(pending_order["quantity"], shares)
                commission = calculate_commission(trade_quantity, trade_price)
                if trade_quantity > 0:
                    shares -= trade_quantity
                    revenue = trade_quantity * trade_price - commission
                    cash += revenue
                    executed_action = "SELL"

            if executed_action != "HOLD":
                trades.append({
                    "ticker": ticker,
                    "date": current_date.isoformat(),
                    "type": executed_action.lower(),
                    "price": trade_price,
                    "quantity": trade_quantity,
                    "position_pct": pending_order["position_pct"],
                    "commission": commission,
                    "cash_after": cash,
                    "shares_after": shares,
                    "signal_date": pending_order["signal_date"],
                    "signal_price": pending_order["signal_price"],
                })
            pending_order = None

        if execution == "same_day_close" and decision:
            action = decision["action"]
            fraction = decision["position_fraction"]
            trade_price = bar["close"]
            if action == "BUY":
                trade_quantity, commission, cash = execute_buy(cash, trade_price, fraction)
                if trade_quantity > 0:
                    shares += trade_quantity
                    executed_action = "BUY"
            elif action == "SELL":
                trade_quantity, commission, revenue = execute_sell(shares, trade_price, fraction)
                if trade_quantity > 0:
                    shares -= trade_quantity
                    cash += revenue
                    executed_action = "SELL"

            if executed_action != "HOLD":
                trades.append({
                    "ticker": ticker,
                    "date": current_date.isoformat(),
                    "type": executed_action.lower(),
                    "price": trade_price,
                    "quantity": trade_quantity,
                    "position_pct": decision["position_pct"],
                    "commission": commission,
                    "cash_after": cash,
                    "shares_after": shares,
                    "signal_date": current_date.isoformat(),
                    "signal_price": bar["close"],
                })

        if execution == "next_day_open" and decision:
            action = decision["action"]
            fraction = decision["position_fraction"]
            if action == "BUY":
                budget = cash * fraction
                order_quantity = adjust_size_for_budget(budget, bar["close"])
            elif action == "SELL":
                order_quantity = shares if fraction >= 1.0 else int(shares * fraction)
            else:
                order_quantity = 0

            pending_order = {
                "action": action,
                "quantity": order_quantity,
                "position_pct": decision["position_pct"],
                "signal_date": current_date.isoformat(),
                "signal_price": bar["close"],
            } if order_quantity > 0 else None

        equity.append({
            "ticker": ticker,
            "date": current_date.isoformat(),
            "open": bar["open"],
            "close": bar["close"],
            "cash": cash,
            "shares": shares,
            "equity": cash + shares * bar["close"],
            "decision_action": decision["action"] if decision else "HOLD",
            "raw_action": decision.get("raw_action", "") if decision else "",
            "position_pct": decision.get("position_pct", 0.0) if decision else 0.0,
            "executed_action": executed_action,
            "trade_quantity": trade_quantity,
            "trade_price": trade_price if executed_action != "HOLD" else "",
            "commission": commission,
        })

    if final_liquidation and shares > 0:
        last_bar = bars[-1]
        trade_quantity = shares
        commission = calculate_commission(trade_quantity, last_bar["close"])
        cash += trade_quantity * last_bar["close"] - commission
        shares = 0
        equity[-1]["cash"] = cash
        equity[-1]["shares"] = shares
        equity[-1]["equity"] = cash
        equity[-1]["executed_action"] = "FINAL_SELL"
        equity[-1]["trade_quantity"] = trade_quantity
        equity[-1]["trade_price"] = last_bar["close"]
        equity[-1]["commission"] = commission
        trades.append({
            "ticker": ticker,
            "date": last_bar["date"].isoformat(),
            "type": "final_sell",
            "price": last_bar["close"],
            "quantity": trade_quantity,
            "position_pct": 100.0,
            "commission": commission,
            "cash_after": cash,
            "shares_after": shares,
        })

    return {
        "ticker": ticker,
        "equity": add_return_columns(equity, initial_cash),
        "trades": trades,
        "final_value": equity[-1]["equity"],
    }


def add_return_columns(equity: list[dict[str, Any]], initial_cash: float) -> list[dict[str, Any]]:
    previous_equity = None
    running_peak = equity[0]["equity"] if equity else initial_cash
    for row in equity:
        value = row["equity"]
        row["daily_return"] = 0.0 if previous_equity is None else value / previous_equity - 1.0
        running_peak = max(running_peak, value)
        row["cumulative_return"] = value / initial_cash - 1.0
        row["drawdown"] = value / running_peak - 1.0
        previous_equity = value
    return equity


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


def calculate_metrics(
    ticker: str,
    simulation: dict[str, Any],
    initial_cash: float,
    risk_free_rate: float,
) -> dict[str, Any]:
    returns = daily_returns(simulation["equity"])
    daily_std = sample_std(returns)
    average_daily_return = sum(returns) / len(returns) if returns else 0.0
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    sharpe = 0.0 if daily_std == 0.0 else (average_daily_return - daily_rf) / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)
    total_return = simulation["final_value"] / initial_cash - 1.0

    return {
        "ticker": ticker,
        "start_date": simulation["equity"][0]["date"],
        "end_date": simulation["equity"][-1]["date"],
        "calendar_days": len(simulation["equity"]),
        "return_days": len(returns),
        "initial_cash": initial_cash,
        "final_value": simulation["final_value"],
        "total_commission": sum(trade["commission"] for trade in simulation["trades"]),
        "trade_count": len(simulation["trades"]),
        "final_cash": simulation["equity"][-1]["cash"],
        "final_shares": simulation["equity"][-1]["shares"],
        "SPR": sharpe,
        "CR": total_return * 100.0,
        "MDD": maximum_drawdown_pct(simulation["equity"]),
        "AV": daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0,
    }


def average_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    average: dict[str, Any] = {
        "ticker": "Average",
        "start_date": "",
        "end_date": "",
    }
    for key in [
        "calendar_days",
        "return_days",
        "initial_cash",
        "final_value",
        "total_commission",
        "trade_count",
        "final_cash",
        "final_shares",
        "SPR",
        "CR",
        "MDD",
        "AV",
    ]:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        average[key] = sum(values) / len(values) if values else ""
    return average


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fieldnames} for row in rows)


def save_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    metrics: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "position_pct_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    write_csv(
        output_dir / "position_pct_metrics.csv",
        metrics,
        [
            "ticker",
            "start_date",
            "end_date",
            "calendar_days",
            "return_days",
            "initial_cash",
            "final_value",
            "total_commission",
            "trade_count",
            "final_cash",
            "final_shares",
            "SPR",
            "CR",
            "MDD",
            "AV",
        ],
    )
    write_csv(
        output_dir / "position_pct_daily_equity.csv",
        equity,
        [
            "ticker",
            "date",
            "open",
            "close",
            "cash",
            "shares",
            "equity",
            "daily_return",
            "cumulative_return",
            "drawdown",
            "decision_action",
            "raw_action",
            "position_pct",
            "executed_action",
            "trade_quantity",
            "trade_price",
            "commission",
        ],
    )
    write_csv(
        output_dir / "position_pct_trades.csv",
        trades,
        [
            "ticker",
            "date",
            "type",
            "price",
            "quantity",
            "position_pct",
            "commission",
            "cash_after",
            "shares_after",
            "signal_date",
            "signal_price",
        ],
    )


def fmt_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def print_table(rows: list[dict[str, Any]]) -> None:
    print("Ticker        SPR        CR       MDD        AV")
    print("------  --------  --------  --------  --------")
    for row in rows:
        print(
            f"{row['ticker']:<7}  "
            f"{fmt_metric(row['SPR']):>8}  "
            f"{fmt_metric(row['CR']):>8}  "
            f"{fmt_metric(row['MDD']):>8}  "
            f"{fmt_metric(row['AV']):>8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay decisions.csv with position_pct as partial buy/sell ratio.")
    parser.add_argument("--decisions", required=True, type=Path, help="Path to decisions.csv.")
    parser.add_argument("--prices-root", type=Path, default=DEFAULT_PRICES_ROOT)
    parser.add_argument("--date-from", help="Inclusive start date. Default: first decision date.")
    parser.add_argument("--date-to", help="Exclusive end date. Default: one day after the last decision date.")
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH)
    parser.add_argument("--risk-free-rate", type=float, default=RISK_FREE_RATE)
    parser.add_argument("--execution", choices=["same_day_close", "next_day_open"], default="same_day_close")
    parser.add_argument("--final-liquidation", action="store_true", help="Sell all remaining shares on the last replay date.")
    parser.add_argument("--include-errors", action="store_true", help="Include non-ok decision rows.")
    parser.add_argument("--output-dir", type=Path, help="Directory for output files.")
    args = parser.parse_args()

    decisions = load_decisions(args.decisions, include_errors=args.include_errors)
    if not decisions:
        raise SystemExit("No usable decision rows found.")

    default_from, default_to = default_date_window(decisions)
    date_from = args.date_from or default_from
    date_to = args.date_to or default_to

    simulations = []
    errors = []
    for ticker, ticker_decisions in sorted(decisions.items()):
        try:
            bars = load_adjusted_bars(args.prices_root, ticker, date_from, date_to)
            simulations.append(
                replay_decisions(
                    ticker=ticker,
                    decisions=ticker_decisions,
                    bars=bars,
                    initial_cash=args.initial_cash,
                    execution=args.execution,
                    final_liquidation=args.final_liquidation,
                )
            )
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})

    if not simulations:
        raise SystemExit(f"No ticker could be evaluated: {errors}")

    metrics = [
        calculate_metrics(
            ticker=simulation["ticker"],
            simulation=simulation,
            initial_cash=args.initial_cash,
            risk_free_rate=args.risk_free_rate,
        )
        for simulation in simulations
    ]
    if len(metrics) > 1:
        metrics.append(average_metrics(metrics))

    equity = [row for simulation in simulations for row in simulation["equity"]]
    trades = [trade for simulation in simulations for trade in simulation["trades"]]
    summary = {
        "decisions_file": str(args.decisions),
        "prices_root": str(args.prices_root),
        "date_from": date_from,
        "date_to_exclusive": date_to,
        "initial_cash_per_ticker": args.initial_cash,
        "risk_free_rate": args.risk_free_rate,
        "execution": args.execution,
        "final_liquidation": args.final_liquidation,
        "position_pct_rule": "BUY uses pct of remaining cash; SELL uses pct of current shares.",
        "metrics": metrics,
        "errors": errors,
    }

    output_dir = args.output_dir or args.decisions.parent / "position_pct_performance"
    save_outputs(output_dir, summary, metrics, equity, trades)
    print_table(metrics)
    print(f"Outputs saved to: {output_dir}")
    if errors:
        print(f"Skipped tickers: {errors}")


if __name__ == "__main__":
    main()
