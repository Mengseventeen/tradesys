# TradeSys Dynamic Team Exercise

This repository contains an offline stock-trading workflow experiment for four tickers: AMZN, MSFT, NFLX, and TSLA.

The project uses local price, technical indicator, fundamental, news, and macroeconomic data under `tradesys/data_portfolio`. The latest submitted experiment is:

`analysis_results/dataevolver_signal_only_latest_20260715_200927`

## Main Scripts

- `run_analysis.py`: generate daily BUY/SELL/HOLD decisions.
- `evaluate_performance.py`: replay decisions with same-day execution.
- `evaluate_position_pct_replay.py`: replay decisions with position percentage and configurable execution timing.
- `evaluate_buy_and_hold.py`: calculate buy-and-hold baseline metrics.

## Latest Result

The latest pushed metrics use second-day open execution:

```powershell
python evaluate_position_pct_replay.py `
  --decisions analysis_results\dataevolver_signal_only_latest_20260715_200927\decisions.csv `
  --execution next_day_open `
  --final-liquidation `
  --output-dir analysis_results\dataevolver_signal_only_latest_20260715_200927\performance_decision_metrics_next_day_open
```

Summary:

| Ticker | SPR | CR | MDD | AV |
| --- | ---: | ---: | ---: | ---: |
| AMZN | 0.252 | 4.618 | -22.530 | 26.536 |
| MSFT | 0.779 | 13.236 | -11.363 | 20.447 |
| NFLX | 0.904 | 19.243 | -13.475 | 27.101 |
| TSLA | 1.174 | 31.823 | -13.144 | 34.247 |
| Average | 0.777 | 17.230 | -15.128 | 27.083 |

