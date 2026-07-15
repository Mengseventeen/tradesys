# Latest Experiment Log

## Decision Generation

- Workflow: `dataevolver`
- Tickers: `AMZN`, `MSFT`, `NFLX`, `TSLA`
- Date range: `2022-10-06` to `2023-04-10`
- Decisions generated: `508`
- Status: `508 ok`
- Decision file: `decisions.csv`

Command used:

```powershell
python run_analysis.py `
  --tickers AMZN MSFT NFLX TSLA `
  --workflow-mode dataevolver `
  --start-date 2022-10-06 `
  --end-date 2023-04-10 `
  --batch-size 64 `
  --results-dir analysis_results\dataevolver_signal_only_latest_20260715_200927
```

## Second-Day Open Replay

Command used:

```powershell
python evaluate_position_pct_replay.py `
  --decisions analysis_results\dataevolver_signal_only_latest_20260715_200927\decisions.csv `
  --execution next_day_open `
  --final-liquidation `
  --output-dir analysis_results\dataevolver_signal_only_latest_20260715_200927\performance_decision_metrics_next_day_open
```

Metrics:

| Ticker | SPR | CR | MDD | AV |
| --- | ---: | ---: | ---: | ---: |
| AMZN | 0.252 | 4.618 | -22.530 | 26.536 |
| MSFT | 0.779 | 13.236 | -11.363 | 20.447 |
| NFLX | 0.904 | 19.243 | -13.475 | 27.101 |
| TSLA | 1.174 | 31.823 | -13.144 | 34.247 |
| Average | 0.777 | 17.230 | -15.128 | 27.083 |

Output files:

- `performance_decision_metrics_next_day_open/position_pct_metrics.csv`
- `performance_decision_metrics_next_day_open/position_pct_summary.json`
- `performance_decision_metrics_next_day_open/position_pct_trades.csv`
- `performance_decision_metrics_next_day_open/position_pct_daily_equity.csv`
