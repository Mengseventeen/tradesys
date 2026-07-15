import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from tradesys.evaluation.common import (
    COMMISSION_PER_SHARE,
    INITIAL_CASH,
    MAX_COMMISSION_RATE,
    MIN_COMMISSION,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    calculate_commission,
    get_column,
    normalize_action,
    parse_date,
    parse_float,
    sample_std,
    write_csv,
)

EXERCISE_ROOT = Path(__file__).parent
PRICES_ROOT = EXERCISE_ROOT / "tradesys" / "data_portfolio" / "stock_data"
PRICE_COLUMN = "adjusted_close"

def load_decisions(path: Path, include_errors: bool = False) -> dict[str, dict[date, dict[str, Any]]]:
    decisions: dict[str, dict[date, dict[str, Any]]] = defaultdict(dict)

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Decision file has no header: {path}")

        fields = {field.lower() for field in reader.fieldnames}
        if "ticker" not in fields:
            raise ValueError("Decision file is missing required column: ticker")
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

            position_pct = parse_float(get_column(row, ("position_pct", "position_size", "position")), 0.0)
            action = normalize_action(get_column(row, ("action", "decision", "signal")), position_pct)
            current_date = parse_date(raw_date)
            decisions[ticker][current_date] = {
                "action": action,
                "raw_action": get_column(row, ("action", "decision", "signal")),
                "position_pct": position_pct,
                "status": status or "ok",
            }

    return dict(decisions)


def load_prices(
    prices_root: Path,
    ticker: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    csv_path = prices_root / ticker / "daily_prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Daily price file not found: {csv_path}")

    prices: list[dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"date", PRICE_COLUMN}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            current_date = parse_date(row["date"])
            if current_date < start_date or current_date > end_date:
                continue
            price = parse_float(row[PRICE_COLUMN], math.nan)
            if not math.isnan(price) and price > 0:
                prices.append({
                    "date": current_date,
                    "price": price,
                })

    return sorted(prices, key=lambda item: item["date"])


def buy_all_available(
    cash: float,
    price: float,
    commission_per_share: float,
    min_commission: float,
    max_commission_rate: float,
) -> tuple[int, float, float]:
    """Mirror FINSABERFrameworkHelper.buy(..., quantity=-1)."""
    if cash < price or price <= 0:
        return 0, 0.0, cash

    total_cost = cash
    initial_quantity = int(total_cost / price)
    commission = calculate_commission(
        initial_quantity,
        price,
        commission_per_share,
        min_commission,
        max_commission_rate,
    )
    total_cost -= commission
    quantity = int(total_cost / price)
    total_cost = price * quantity + commission

    if quantity <= 0 or cash < total_cost:
        return 0, 0.0, cash
    return quantity, commission, cash - total_cost


def replay_ticker(
    ticker: str,
    ticker_decisions: dict[date, dict[str, Any]],
    prices_root: Path,
    initial_cash: float,
    risk_free_rate: float,
    commission_per_share: float,
    min_commission: float,
    max_commission_rate: float,
    start_date: date | None,
    end_date: date | None,
    liquidate_final: bool,
) -> dict[str, Any]:
    if not ticker_decisions:
        raise ValueError(f"No decisions found for {ticker}")

    replay_start = start_date or min(ticker_decisions)
    replay_end = end_date or max(ticker_decisions)
    prices = load_prices(prices_root, ticker, replay_start, replay_end)
    if len(prices) < 2:
        raise ValueError(f"Not enough price rows for {ticker} in {replay_start} to {replay_end}")

    cash = initial_cash
    shares = 0
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    previous_equity: float | None = None
    running_peak = 0.0

    for bar in prices:
        current_date = bar["date"]
        price = bar["price"]
        decision = ticker_decisions.get(current_date, {"action": "HOLD", "position_pct": 0.0, "raw_action": ""})
        action = decision["action"]
        executed_action = "HOLD"
        trade_quantity = 0
        commission = 0.0

        if action == "BUY" and cash >= price:
            quantity, commission, cash_after = buy_all_available(
                cash,
                price,
                commission_per_share,
                min_commission,
                max_commission_rate,
            )
            if quantity > 0:
                cash = cash_after
                shares += quantity
                executed_action = "BUY"
                trade_quantity = quantity
                trades.append({
                    "date": current_date.isoformat(),
                    "ticker": ticker,
                    "type": "buy",
                    "price": price,
                    "quantity": quantity,
                    "commission": commission,
                    "cash_after": cash,
                    "shares_after": shares,
                })
        elif action == "SELL" and shares > 0:
            trade_quantity = shares
            commission = calculate_commission(
                trade_quantity,
                price,
                commission_per_share,
                min_commission,
                max_commission_rate,
            )
            cash += price * trade_quantity - commission
            shares = 0
            executed_action = "SELL"
            trades.append({
                "date": current_date.isoformat(),
                "ticker": ticker,
                "type": "sell",
                "price": price,
                "quantity": trade_quantity,
                "commission": commission,
                "cash_after": cash,
                "shares_after": shares,
            })

        equity = cash + shares * price
        daily_return = 0.0 if previous_equity is None else equity / previous_equity - 1.0
        running_peak = equity if previous_equity is None else max(running_peak, equity)
        drawdown = equity / running_peak - 1.0 if running_peak > 0 else 0.0
        equity_rows.append({
            "ticker": ticker,
            "date": current_date.isoformat(),
            "price": price,
            "cash": cash,
            "shares": shares,
            "equity": equity,
            "daily_return": daily_return,
            "cumulative_return": equity / initial_cash - 1.0,
            "drawdown": drawdown,
            "decision_action": action,
            "raw_action": decision.get("raw_action", ""),
            "position_pct": decision.get("position_pct", 0.0),
            "executed_action": executed_action,
            "trade_quantity": trade_quantity,
            "commission": commission,
        })
        previous_equity = equity

    final_price = prices[-1]["price"]
    final_date = prices[-1]["date"]
    if liquidate_final and shares > 0:
        quantity = shares
        commission = calculate_commission(
            quantity,
            final_price,
            commission_per_share,
            min_commission,
            max_commission_rate,
        )
        cash += final_price * quantity - commission
        shares = 0
        trades.append({
            "date": final_date.isoformat(),
            "ticker": ticker,
            "type": "final_sell",
            "price": final_price,
            "quantity": quantity,
            "commission": commission,
            "cash_after": cash,
            "shares_after": shares,
        })

    final_value = cash + shares * final_price
    metrics = calculate_metrics(
        ticker=ticker,
        equity_rows=equity_rows,
        final_value=final_value,
        initial_cash=initial_cash,
        risk_free_rate=risk_free_rate,
        date_count=len(prices),
        total_commission=sum(trade["commission"] for trade in trades),
    )

    return {
        "ticker": ticker,
        "start_date": prices[0]["date"].isoformat(),
        "end_date": prices[-1]["date"].isoformat(),
        "equity": equity_rows,
        "trades": trades,
        "metrics": metrics,
    }


def calculate_metrics(
    ticker: str,
    equity_rows: list[dict[str, Any]],
    final_value: float,
    initial_cash: float,
    risk_free_rate: float,
    date_count: int,
    total_commission: float,
) -> dict[str, Any]:
    returns = [row["daily_return"] for row in equity_rows[1:]]
    total_return = final_value / initial_cash - 1.0
    annual_return = (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / date_count) - 1.0
    annual_volatility = sample_std(returns) * math.sqrt(TRADING_DAYS_PER_YEAR)
    downside_returns = [value for value in returns if value < 0]
    downside_deviation = sample_std(downside_returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if len(downside_returns) > 1 else 0.0
    mean_daily_return = sum(returns) / len(returns) if returns else 0.0
    sharpe_ratio = (
        (mean_daily_return * TRADING_DAYS_PER_YEAR - risk_free_rate) / annual_volatility
        if annual_volatility > 0
        else 0.0
    )
    sortino_ratio = (
        (mean_daily_return * TRADING_DAYS_PER_YEAR - risk_free_rate) / downside_deviation
        if downside_deviation > 0
        else 0.0
    )
    max_drawdown = min((row["drawdown"] for row in equity_rows), default=0.0)

    return {
        "ticker": ticker,
        "start_date": equity_rows[0]["date"],
        "end_date": equity_rows[-1]["date"],
        "days": date_count,
        "return_days": len(returns),
        "initial_cash": initial_cash,
        "final_value": final_value,
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "total_commission": total_commission,
        "max_drawdown": max_drawdown,
        "SPR": sharpe_ratio,
        "CR": total_return * 100.0,
        "MDD": max_drawdown * 100.0,
        "AV": annual_volatility * 100.0,
    }


def average_metrics(metrics_rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_keys = [
        "days",
        "return_days",
        "initial_cash",
        "final_value",
        "total_return",
        "annual_return",
        "annual_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "total_commission",
        "max_drawdown",
        "SPR",
        "CR",
        "MDD",
        "AV",
    ]
    average: dict[str, Any] = {
        "ticker": "Average",
        "start_date": "",
        "end_date": "",
    }
    for key in numeric_keys:
        values = [row[key] for row in metrics_rows if isinstance(row.get(key), (int, float))]
        average[key] = sum(values) / len(values) if values else ""
    return average


def save_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    metrics_rows: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "performance_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    metrics_fields = [
        "ticker",
        "start_date",
        "end_date",
        "days",
        "return_days",
        "initial_cash",
        "final_value",
        "total_return",
        "annual_return",
        "annual_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "total_commission",
        "max_drawdown",
        "SPR",
        "CR",
        "MDD",
        "AV",
    ]
    equity_fields = [
        "ticker",
        "date",
        "price",
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
        "commission",
    ]
    trade_fields = [
        "date",
        "ticker",
        "type",
        "price",
        "quantity",
        "commission",
        "cash_after",
        "shares_after",
    ]

    write_csv(output_dir / "metrics_by_ticker.csv", metrics_rows, metrics_fields)
    write_csv(output_dir / "daily_equity.csv", equity_rows, equity_fields)
    write_csv(output_dir / "trades.csv", trades, trade_fields)

    write_csv(
        output_dir / "daily_returns.csv",
        equity_rows,
        ["ticker", "date", "daily_return", "equity", "cumulative_return", "drawdown"],
    )


def fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def fmt_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.4f}"


def print_metrics_table(metrics_rows: list[dict[str, Any]]) -> None:
    print("Ticker        SPR        CR       MDD        AV")
    print("------  --------  --------  --------  --------")
    for row in metrics_rows:
        print(
            f"{row['ticker']:<7}"
            f"{row['SPR']:>9.3f}"
            f"{row['CR']:>10.3f}"
            f"{row['MDD']:>10.3f}"
            f"{row['AV']:>10.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay decisions.csv with FINSABER ISO-style cash/position accounting."
    )
    parser.add_argument("--decisions", required=True, type=Path, help="Path to decisions.csv.")
    parser.add_argument("--prices-root", type=Path, default=PRICES_ROOT, help="Root folder containing TICKER/daily_prices.csv.")
    parser.add_argument("--output-dir", type=Path, help="Directory for performance output files.")
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH, help="Initial cash per ticker.")
    parser.add_argument("--risk-free-rate", type=float, default=RISK_FREE_RATE, help="Annual risk-free rate as decimal.")
    parser.add_argument("--commission-per-share", type=float, default=COMMISSION_PER_SHARE)
    parser.add_argument("--min-commission", type=float, default=MIN_COMMISSION)
    parser.add_argument("--max-commission-rate", type=float, default=MAX_COMMISSION_RATE)
    parser.add_argument("--start-date", type=str, help="Optional replay start date, inclusive.")
    parser.add_argument("--end-date", type=str, help="Optional replay end date, inclusive.")
    parser.add_argument("--include-errors", action="store_true", help="Include non-ok decision rows.")
    parser.add_argument("--no-final-liquidation", action="store_true", help="Do not force-sell remaining shares on the last date.")
    parser.add_argument(
        "--execution",
        choices=["next_day", "same_day"],
        default="same_day",
        help="Accepted for old scripts; FINSABER ISO replay always executes on the decision date.",
    )
    parser.add_argument(
        "--include-next-day",
        action="store_true",
        help="Accepted for old scripts; ignored by FINSABER ISO replay.",
    )
    args = parser.parse_args()

    decisions = load_decisions(args.decisions, include_errors=args.include_errors)
    if not decisions:
        raise SystemExit("No usable decision rows found.")

    start_date = parse_date(args.start_date) if args.start_date else None
    end_date = parse_date(args.end_date) if args.end_date else None

    results = []
    errors = []
    for ticker, ticker_decisions in sorted(decisions.items()):
        try:
            results.append(
                replay_ticker(
                    ticker=ticker,
                    ticker_decisions=ticker_decisions,
                    prices_root=args.prices_root,
                    initial_cash=args.initial_cash,
                    risk_free_rate=args.risk_free_rate,
                    commission_per_share=args.commission_per_share,
                    min_commission=args.min_commission,
                    max_commission_rate=args.max_commission_rate,
                    start_date=start_date,
                    end_date=end_date,
                    liquidate_final=not args.no_final_liquidation,
                )
            )
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})

    if not results:
        raise SystemExit(f"No ticker could be evaluated: {errors}")

    metrics_rows = [result["metrics"] for result in results]
    if len(metrics_rows) > 1:
        metrics_rows.append(average_metrics(metrics_rows))
    equity_rows = [row for result in results for row in result["equity"]]
    trades = [trade for result in results for trade in result["trades"]]

    summary = {
        "decisions_file": str(args.decisions),
        "prices_root": str(args.prices_root),
        "price_column": PRICE_COLUMN,
        "logic": "FINSABER ISO replay",
        "execution": "same_day",
        "initial_cash_per_ticker": args.initial_cash,
        "risk_free_rate": args.risk_free_rate,
        "commission_per_share": args.commission_per_share,
        "min_commission": args.min_commission,
        "max_commission_rate": args.max_commission_rate,
        "final_liquidation": not args.no_final_liquidation,
        "tickers": [result["ticker"] for result in results],
        "metrics": metrics_rows,
        "errors": errors,
    }

    output_dir = args.output_dir or args.decisions.parent / "performance"
    save_outputs(output_dir, summary, metrics_rows, equity_rows, trades)

    print_metrics_table(metrics_rows)
    print(f"Outputs saved to: {output_dir}")
    if errors:
        print(f"Skipped tickers: {errors}")


if __name__ == "__main__":
    main()
