# Results Index

This folder keeps only the result files that are useful for review or paper comparison.

## Best Run: DataEvolver Signal-Only

Path:

`analysis_results/dataevolver_signal_only_latest_20260715_200927`

Use this as the current best-performing trajectory/result package.

- `decisions.csv`: all 508 daily decisions.
- `decision_results_compact.csv`: compact decision table.
- `RUN_LOG.md`: reproducibility log with commands and metrics.
- `debug_runs/*.json`: full per-date trajectories. Each file contains local evidence, reports, workflow plan, DAG/node outputs, final decision, and status.
- `performance_decision_metrics_next_day_open/`: financial metrics using next-day-open execution.

The teacher's "trajectory" most likely refers to the `debug_runs/*.json` files.

The teacher's "log" is represented by `RUN_LOG.md` plus the evaluation summaries, because this latest run was not redirected to a raw `stdout.log`.

## Comparison Baseline: LLMCompiler Agent Eval Retry

Path:

`analysis_results/full_llmcompiler_agent_eval_retry`

This is included as a lightweight comparison baseline for paper writing.

- `decisions.csv`: LLMCompiler decisions.
- `decision_results_compact.csv`: compact LLMCompiler decisions.
- `full_run_stdout.log`, `resume_stdout_4w.log`, `quality_repair_stdout*.log`: raw run/repair logs.
- `position_pct_performance_final/position_pct_metrics.csv`: final LLMCompiler metrics.
- `technical_guard_performance/position_pct_metrics.csv`: technical-guard comparison metrics.
- `buy_and_hold_baseline_final/buy_and_hold_finsaber_metrics.csv`: buy-and-hold baseline.
- `{AMZN,MSFT,NFLX,TSLA}/debug_runs/*_2023-04-10_debug.json`: final-day sample trajectories for the comparison method.

Large redundant files such as `all_results.json`, `multi_ticker_results.json`, and full historical debug folders are intentionally not tracked.
