# TradeSys: LangGraph Analysts + DataEvolver LLM DAG

This repository contains one stock-trading research workflow for AMZN, MSFT, NFLX, and TSLA:

1. Four LangGraph analysts use one programmatic data-collection tool each to produce technical, fundamental, news, and policy reports with fewer model/tool round trips.
2. DataEvolver uses an LLM-driven data-understanding, free-fitting, template-combination, and constrained-search process to build the trading DAG.
3. Seven evaluated LLM agents execute the DAG: `read_market_data`, `bullish_signal`, `bearish_signal`, `disagreement_detection`, `risk_management`, `position_sizing`, and `join`.
4. The final decision is written as BUY, SELL, or HOLD with a percentage position.

An OpenAI-compatible API is required. Configure `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_TIMEOUT`, and `OPENAI_MAX_RETRIES` in the environment or a supported `.env` file.

## Run

Single date:

```powershell
python run_analysis.py --ticker AMZN --date 2023-04-10
```

Choose one of three execution modes:

```powershell
python run_analysis.py --ticker AMZN --date 2023-04-10 --execution-mode baseline
python run_analysis.py --ticker AMZN --date 2023-04-10 --execution-mode static_ptc
python run_analysis.py --ticker AMZN --date 2023-04-10 --execution-mode dynamic_ptc
```

- `baseline`: sequential execution of the current seven-agent DAG.
- `static_ptc`: compile the same DAG to validated PTC IR and execute dependency-ready layers in parallel.
- `dynamic_ptc`: compile a conditional PTC program that may replace bullish, bearish, or disagreement calls with safe constants based on the market regime.

PTC programs are not passed to Python `exec`. The runtime accepts only registered tool calls and validated constant instructions, checks dependencies and output schemas, and records the rendered program plus its call trace.

Multi-ticker batch:

```powershell
python run_analysis.py `
  --tickers AMZN MSFT NFLX TSLA `
  --start-date 2022-10-06 `
  --end-date 2023-04-10 `
  --batch-size 8 `
  --results-dir analysis_results\dataevolver_llm_run
```

The run writes `decisions.csv`, per-date debug trajectories, analyst reports, DAG plans, node outputs, quality evaluations, and final decisions.

## Evaluate

Replay percentage decisions at the next trading day's open:

```powershell
python evaluate_position_pct_replay.py `
  --decisions analysis_results\dataevolver_llm_run\decisions.csv `
  --execution next_day_open `
  --final-liquidation `
  --output-dir analysis_results\dataevolver_llm_run\performance_next_day_open
```

Use `evaluate_buy_and_hold.py` to create a buy-and-hold comparison baseline. Existing folders under `analysis_results` are retained as historical experiment records and may refer to workflows that are no longer present in the codebase.

## PTC Ablation

Run the baseline, static PTC, and dynamic PTC experiments over identical inputs:

```powershell
python run_ptc_ablation.py `
  --tickers AMZN MSFT NFLX TSLA `
  --start-date 2022-10-06 `
  --end-date 2023-04-10 `
  --workers 8 `
  --results-dir analysis_results\ptc_ablation_full
```

The runner evaluates every mode with next-day-open execution and writes `ablation_summary.json` and `ablation_summary.csv`, including financial metrics, runtime, errors, average LLM tool calls, skipped calls, execution layers, action counts, and dynamic routing frequencies.
