# Optimized DAG v1 Experiment

## Scope

- Workflow: `optimized_dag_ma10_exit_vol_guard_v1`
- Tickers: `AMZN, MSFT, NFLX, TSLA`
- Date range: `2022-10-06` to `2023-04-10`
- Decisions generated: `508`
- Trajectory files: `debug_runs/*.json`

## DAG

1. `read_market_data`
2. `trend_confirmation`
3. `risk_gate`
4. `position_sizing`
5. `join`

## Rule

- SELL when adjusted close is below MA10.
- BUY rebound when `from_low20_pct >= 5`, close is above MA10, RSI is at least 45, and ATR/close volatility is at most 4%.
- BUY repair when 60-day drawdown is at most -15%, RSI is at least 45, stochastic %K is at least 50, and close is above MA10.
- HOLD otherwise.

## Evaluation Command

```powershell
python evaluate_position_pct_replay.py --decisions analysis_results\optimized_dag_v1_20260716_040158\decisions.csv --execution next_day_open --final-liquidation --output-dir analysis_results\optimized_dag_v1_20260716_040158\performance_next_day_open
```
