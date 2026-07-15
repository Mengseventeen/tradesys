import argparse
import json
import math
from pathlib import Path
from typing import Any

from tradesys.evaluation.common import (
    DEFAULT_TICKERS,
    INITIAL_CASH,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    adjust_size_for_budget,
    calculate_commission,
    daily_returns,
    load_adjusted_bars,
    maximum_drawdown_pct,
    sample_std,
    write_csv,
)

EXERCISE_ROOT = Path(__file__).parent
DEFAULT_PRICES_ROOT = EXERCISE_ROOT / "tradesys" / "data_portfolio" / "stock_data"


def run_buy_and_hold(
    bars: list[dict[str, Any]],
    initial_cash: float,
) -> dict[str, Any]:
    """Backtrader-style buy and hold: signal on first bar, market buy on next bar open."""
    cash = initial_cash
    shares = 0
    pending_buy_size = None
    equity = []
    trade = {}

    for bar in bars:
        if pending_buy_size:
            price = bar["open"]
            commission = calculate_commission(pending_buy_size, price)
            total_cost = pending_buy_size * price + commission
            if cash >= total_cost:
                cash -= total_cost
                shares += pending_buy_size
                trade = {
                    "signal_date": trade["signal_date"],
                    "execution_date": bar["date"].isoformat(),
                    "shares": pending_buy_size,
                    "signal_close": trade["signal_close"],
                    "execution_open": price,
                    "commission": commission,
                }
            pending_buy_size = None

        if shares == 0 and pending_buy_size is None:
            pending_buy_size = adjust_size_for_budget(cash, bar["close"])
            trade = {
                "signal_date": bar["date"].isoformat(),
                "signal_close": bar["close"],
            }

        equity.append({
            "date": bar["date"].isoformat(),
            "equity": cash + shares * bar["close"],
            "cash": cash,
            "shares": shares,
            "close": bar["close"],
        })

    return {
        "equity": equity,
        "trade": trade,
        "final_value": equity[-1]["equity"],
    }


def calculate_metrics(ticker: str, bars: list[dict[str, Any]], initial_cash: float, risk_free_rate: float) -> dict[str, Any]:
    simulation = run_buy_and_hold(bars, initial_cash)
    returns = daily_returns(simulation["equity"])
    daily_std = sample_std(returns)
    average_daily_return = sum(returns) / len(returns) if returns else 0.0
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    sharpe = 0.0 if daily_std == 0.0 else (average_daily_return - daily_rf) / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)
    total_return = simulation["final_value"] / initial_cash - 1.0

    trade = simulation["trade"]
    return {
        "ticker": ticker,
        "start_date": bars[0]["date"].isoformat(),
        "end_date": bars[-1]["date"].isoformat(),
        "calendar_days": len(bars),
        "return_days": len(returns),
        "initial_cash": initial_cash,
        "final_value": simulation["final_value"],
        "signal_date": trade.get("signal_date", ""),
        "execution_date": trade.get("execution_date", ""),
        "shares": trade.get("shares", 0),
        "signal_close": trade.get("signal_close", 0.0),
        "execution_open": trade.get("execution_open", 0.0),
        "commission": trade.get("commission", 0.0),
        "SPR": sharpe,
        "CR": total_return * 100.0,
        "MDD": maximum_drawdown_pct(simulation["equity"]),
        "AV": daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0,
    }


def save_outputs(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "buy_and_hold_finsaber_metrics.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    write_csv(
        output_dir / "buy_and_hold_finsaber_metrics.csv",
        rows,
        [
            "ticker",
            "start_date",
            "end_date",
            "calendar_days",
            "return_days",
            "initial_cash",
            "final_value",
            "signal_date",
            "execution_date",
            "shares",
            "signal_close",
            "execution_open",
            "commission",
            "SPR",
            "CR",
            "MDD",
            "AV",
        ],
    )


def fmt_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def print_table(rows: list[dict[str, Any]]) -> None:
    print("Ticker        SPR        CR       MDD        AV")
    print("------  --------  --------  --------  --------")
    for row in rows:
        print(
            f"{row['ticker']:<6}  "
            f"{fmt_metric(row['SPR']):>8}  "
            f"{fmt_metric(row['CR']):>8}  "
            f"{fmt_metric(row['MDD']):>8}  "
            f"{fmt_metric(row['AV']):>8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate FINSABER-style buy-and-hold metrics.")
    parser.add_argument("--prices-root", type=Path, default=DEFAULT_PRICES_ROOT)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--date-from", default="2022-10-06")
    parser.add_argument("--date-to", default="2023-04-10", help="Exclusive end date, matching FINSABER.")
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH)
    parser.add_argument("--risk-free-rate", type=float, default=RISK_FREE_RATE)
    parser.add_argument("--output-dir", type=Path, default=EXERCISE_ROOT / "buy_and_hold_results")
    args = parser.parse_args()

    rows = [
        calculate_metrics(
            ticker=ticker.upper(),
            bars=load_adjusted_bars(args.prices_root, ticker.upper(), args.date_from, args.date_to),
            initial_cash=args.initial_cash,
            risk_free_rate=args.risk_free_rate,
        )
        for ticker in args.tickers
    ]

    save_outputs(args.output_dir, rows)
    print_table(rows)
    print(f"Outputs saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
