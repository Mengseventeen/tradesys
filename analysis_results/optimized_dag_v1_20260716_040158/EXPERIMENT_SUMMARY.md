# Optimized DAG v1 Full Experiment

## Scope

- Script: `run_optimized_dag_experiment.py`
- Workflow: `optimized_dag_ma10_exit_vol_guard_v1`
- Tickers: `AMZN`, `MSFT`, `NFLX`, `TSLA`
- Date range: `2022-10-06` to `2023-04-10`
- Decisions generated: `508`
- Trajectory files: `debug_runs/*.json`
- Evaluation: `next_day_open` with final liquidation

## DAG Rule

The baseline signal-only DAG used:

`read_market_data -> risk_management -> join`

This optimized DAG uses:

`read_market_data -> trend_confirmation -> risk_gate -> position_sizing -> join`

Rule details:

- `SELL` when adjusted close is below MA10.
- `BUY` rebound when `from_low20_pct >= 5`, close is above MA10, RSI is at least 45, and ATR/close volatility is at most 4%.
- `BUY` repair when 60-day drawdown is at most `-15%`, RSI is at least 45, stochastic %K is at least 50, and close is above MA10.
- `HOLD` otherwise.

## Results

### Optimized DAG v1

| Ticker | SPR | CR | MDD | AV | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| AMZN | 0.230 | 4.171 | -22.530 | 26.003 | 14 |
| MSFT | 1.018 | 16.724 | -11.438 | 19.509 | 21 |
| NFLX | 1.381 | 18.766 | -6.023 | 15.568 | 13 |
| TSLA | 1.818 | 46.906 | -7.872 | 29.330 | 6 |
| Average | 1.112 | 21.642 | -11.966 | 22.602 | 13.5 |

### Previous Best: DataEvolver Signal-Only

| Ticker | SPR | CR | MDD | AV | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| AMZN | 0.252 | 4.618 | -22.530 | 26.536 | 12 |
| MSFT | 0.779 | 13.236 | -11.363 | 20.447 | 16 |
| NFLX | 0.904 | 19.243 | -13.475 | 27.101 | 16 |
| TSLA | 1.174 | 31.823 | -13.144 | 34.247 | 14 |
| Average | 0.777 | 17.230 | -15.128 | 27.083 | 14.5 |

## Conclusion

Under the `next_day_open` evaluation used for the latest comparison, the optimized DAG improves the full-period average metrics versus the previous best:

- SPR: `0.777 -> 1.112`
- CR: `17.230% -> 21.642%`
- MDD: `-15.128% -> -11.966%`
- AV: `27.083% -> 22.602%`

AMZN is slightly worse on SPR/CR, but the aggregate result is materially better because MSFT, NFLX, and TSLA improve risk-adjusted performance. This run is worth keeping as the new best candidate.

Important caveat: a same-day-close sanity check does not beat the previous best same-day result. Same-day-close average metrics for this optimized DAG are `SPR=0.676`, `CR=15.327`, `MDD=-11.671`, `AV=21.762`. Treat this as a next-day-open optimized candidate, not a universally dominant strategy.

## Files

- `decisions.csv`: full decision output.
- `decision_results_compact.csv`: compact decision output.
- `debug_runs/*.json`: per-date trajectory files.
- `performance_next_day_open/position_pct_metrics.csv`: financial metrics.
- `performance_next_day_open/position_pct_summary.json`: replay summary.
- `performance_same_day_close/position_pct_metrics.csv`: same-day-close sanity check metrics.
