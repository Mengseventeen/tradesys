import argparse
import csv
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # Local fallback mode should not require PyYAML.
    yaml = None


EXERCISE_ROOT = Path(__file__).parent
PROJECT_ROOT = EXERCISE_ROOT.parent
sys.path.insert(0, str(EXERCISE_ROOT))


def load_env_files() -> None:
    env_files = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "tradesys" / ".env",
        EXERCISE_ROOT / ".env",
        EXERCISE_ROOT / "tradesys" / ".env",
    ]

    for env_file in env_files:
        if not env_file.exists():
            continue

        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def load_config() -> dict:
    if yaml is None:
        return {}
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def create_llm():
    from langchain_openai import ChatOpenAI

    config = load_config()
    profile = config.get("llm_profiles", {}).get("openai", {})

    base_url = os.environ.get("OPENAI_BASE_URL") or profile.get("base_url", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL") or profile.get("model", "gpt-4o-mini")
    timeout = int(os.environ.get("OPENAI_TIMEOUT") or profile.get("timeout_sec", 360))
    max_retries = int(os.environ.get("OPENAI_MAX_RETRIES") or profile.get("max_retries", 0))
    api_key = os.environ.get("OPENAI_API_KEY", "")

    return ChatOpenAI(
        base_url=base_url,
        model=model,
        temperature=0.2,
        max_tokens=4000,
        timeout=timeout,
        max_retries=max_retries,
        api_key=api_key,
    )


def json_safe(value: Any):
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def message_debug(messages: list[Any]) -> list[dict]:
    result = []
    for index, message in enumerate(messages or []):
        content = getattr(message, "content", "")
        result.append({
            "index": index,
            "type": getattr(message, "type", type(message).__name__),
            "content": str(content)[:2000],
            "content_truncated": len(str(content)) > 2000,
            "tool_calls": json_safe(getattr(message, "tool_calls", None) or []),
            "name": getattr(message, "name", None),
        })
    return result


def build_debug_payload(ticker: str, trade_date: str, state: dict, error: str = "") -> dict:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "status": "error" if error else "ok",
        "reports": {
            "technical": state.get("technical_report", ""),
            "fundamental": state.get("fundamental_report", ""),
            "news": state.get("news_report", ""),
            "policy": state.get("policy_report", ""),
        },
        "messages": {
            "technical": message_debug(state.get("technical_messages", [])),
            "fundamental": message_debug(state.get("fundamental_messages", [])),
            "news": message_debug(state.get("news_messages", [])),
            "policy": message_debug(state.get("policy_messages", [])),
        },
        "workflow": {
            "workflow_method": state.get("workflow_method", ""),
            "workflow_mode": state.get("workflow_mode", ""),
            "workflow_status": state.get("workflow_status", ""),
            "workflow_plan": state.get("workflow_plan", state.get("team_plan", {})),
            "workflow_outputs": state.get("workflow_outputs", state.get("module_outputs", {})),
            "local_evidence": state.get("local_evidence", {}),
            "final_decision": state.get("final_decision", ""),
        },
        "error": error or state.get("error", ""),
        "state_keys": sorted(str(key) for key in state.keys()),
    }


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(json_safe(data), f, ensure_ascii=False, indent=2)


def get_trading_dates(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit_dates: int = 0,
) -> list[str]:
    csv_path = EXERCISE_ROOT / "tradesys" / "data_portfolio" / "stock_data" / ticker / "daily_prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Daily price data not found: {csv_path}")

    start_dt = _parse_date(start_date) if start_date else None
    end_dt = _parse_date(end_date) if end_date else None
    dates = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            trade_date = row.get("date", "")
            if not trade_date:
                continue
            trade_dt = _parse_date(trade_date)
            if start_dt and trade_dt < start_dt:
                continue
            if end_dt and trade_dt > end_dt:
                continue
            dates.append(trade_date)

    dates = sorted(set(dates), key=_parse_date)
    if limit_dates > 0:
        dates = dates[:limit_dates]
    return dates


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _parse_final_decision(decision_text: str) -> dict:
    action = "HOLD"
    position_pct = 0.0
    allocation_posture = ""
    for line in (decision_text or "").splitlines():
        key, _, value = line.partition(":")
        normalized_key = key.strip().lower()
        if normalized_key == "final decision":
            candidate = value.strip().upper()
            if candidate in {"BUY", "SELL", "SHORT", "HOLD"}:
                action = candidate
        elif normalized_key in {"position percentage", "position pct", "position ratio", "position size"}:
            position_pct = _parse_optional_pct(value)
        elif normalized_key == "allocation posture":
            allocation_posture = value.strip()
    return {
        "action": action,
        "position_pct": position_pct,
        "position_pct_display": _format_position_pct(position_pct),
        "allocation_posture": allocation_posture,
        "position_size": position_pct,
    }


def _parse_optional_pct(value: str) -> float:
    cleaned = value.strip().replace("%", "").replace(",", "")
    try:
        return min(100.0, max(-100.0, float(cleaned)))
    except ValueError:
        return 0.0


def _format_position_pct(value: float | None) -> str:
    if value is None:
        value = 0.0
    return f"{value:.2f}%"


def _decision_fields(final_state: dict, decision_text: str) -> dict:
    parsed = _parse_final_decision(decision_text)
    structured = final_state.get("final_decision_structured", {})
    if not isinstance(structured, dict):
        return parsed

    position_pct = structured.get("position_pct", structured.get("position_size", parsed["position_pct"]))
    try:
        position_pct = min(100.0, max(-100.0, float(position_pct)))
    except (TypeError, ValueError):
        position_pct = parsed["position_pct"]

    return {
        "action": str(structured.get("action") or parsed["action"]).upper(),
        "position_pct": position_pct,
        "position_pct_display": structured.get("position_pct_display") or _format_position_pct(position_pct),
        "allocation_posture": structured.get("allocation_posture") or parsed.get("allocation_posture", ""),
        "position_size": position_pct,
        "max_position_pct": structured.get("max_position_pct"),
        "max_buy_position_pct": structured.get("max_buy_position_pct", structured.get("max_position_pct")),
    }


def run_single_analysis(
    ticker: str,
    trade_date: str,
    results_dir: Path,
    recursion_limit: int,
    max_position_pct: float = 100.0,
    write_all_results: bool = True,
    execution_mode: str = "baseline",
) -> dict:
    reports_dir = results_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TRADESYS_REPORTS_DIR"] = str(reports_dir)

    final_state = {}
    error = ""

    try:
        final_state = _run_langgraph_workflow(
            ticker,
            trade_date,
            recursion_limit,
            max_position_pct,
            execution_mode,
        )
    except Exception:
        error = traceback.format_exc()
        final_state = {
            "ticker": ticker,
            "trade_date": trade_date,
            "technical_report": "",
            "fundamental_report": "",
            "news_report": "",
            "policy_report": "",
            "team_plan": {},
            "generated_skills": [],
            "expert_agents": [],
            "expert_outputs": [],
            "module_outputs": {},
            "team_discussion_summary": "",
            "final_decision_structured": {},
            "final_decision": "",
            "local_evidence": {},
            "workflow_method": "",
            "workflow_plan": {},
            "workflow_outputs": {},
            "workflow_status": "error",
            "error": error,
        }
    if not error and final_state.get("error"):
        error = str(final_state.get("error"))

    debug_payload = build_debug_payload(ticker, trade_date, final_state, error)
    debug_file = results_dir / "debug_runs" / f"{ticker}_{trade_date}_debug.json"
    save_json(debug_file, debug_payload)

    result = {
        "ticker": ticker,
        "trade_date": trade_date,
        "status": "error" if error else "ok",
        "debug_file": str(debug_file),
        "technical_report": final_state.get("technical_report", ""),
        "fundamental_report": final_state.get("fundamental_report", ""),
        "news_report": final_state.get("news_report", ""),
        "policy_report": final_state.get("policy_report", ""),
        "team_plan": final_state.get("team_plan", {}),
        "generated_skills": final_state.get("generated_skills", []),
        "expert_agents": final_state.get("expert_agents", []),
        "expert_outputs": final_state.get("expert_outputs", []),
        "module_outputs": final_state.get("module_outputs", {}),
        "team_discussion_summary": final_state.get("team_discussion_summary", ""),
        "local_evidence": final_state.get("local_evidence", {}),
        "workflow_method": final_state.get("workflow_method", ""),
        "workflow_plan": final_state.get("workflow_plan", {}),
        "workflow_outputs": final_state.get("workflow_outputs", {}),
        "workflow_status": final_state.get("workflow_status", ""),
        "final_decision_structured": final_state.get("final_decision_structured", {}),
        "final_decision": final_state.get("final_decision", ""),
        "error": error,
    }
    result.update(_decision_fields(final_state, result["final_decision"]))
    if write_all_results:
        save_batch_outputs(results_dir, ticker, [result])
    return result


def _run_langgraph_workflow(
    ticker: str,
    trade_date: str,
    recursion_limit: int,
    max_position_pct: float,
    execution_mode: str,
) -> dict:
    from tradesys.graph import Propagator, create_workflow

    llm = create_llm()
    graph = create_workflow(llm)
    propagator = Propagator(
        recursion_limit=recursion_limit,
        max_position_pct=max_position_pct,
        execution_mode=execution_mode,
    )
    initial_state = propagator.create_initial_state(ticker, trade_date)
    return graph.invoke(
        initial_state,
        config=propagator.get_graph_config(),
    )

def save_batch_outputs(results_dir: Path, ticker: str, results: list[dict]) -> None:
    sorted_results = sorted(results, key=lambda item: (item.get("ticker", ""), item.get("trade_date", "")))
    save_json(results_dir / "all_results.json", sorted_results)
    save_json(results_dir / f"{ticker}_results.json", sorted_results)

    csv_path = results_dir / "decisions.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker",
            "trade_date",
            "status",
            "workflow_method",
            "workflow_status",
            "action",
            "position_pct",
            "allocation_posture",
            "max_buy_position_pct",
            "debug_file",
        ])
        for result in sorted_results:
            writer.writerow([
                result.get("ticker", ""),
                result.get("trade_date", ""),
                result.get("status", ""),
                result.get("workflow_method", ""),
                result.get("workflow_status", ""),
                result.get("action", "HOLD"),
                result.get("position_pct", 0.0),
                result.get("allocation_posture", ""),
                result.get("max_buy_position_pct", result.get("max_position_pct", "")),
                result.get("debug_file", ""),
            ])

    compact_path = results_dir / "decision_results_compact.csv"
    with open(compact_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "trade_date", "decision", "position_pct"])
        for result in sorted_results:
            writer.writerow([
                result.get("ticker", ""),
                result.get("trade_date", ""),
                str(result.get("action", "HOLD")).lower(),
                result.get("position_pct", 0.0),
            ])


def run_batch_analysis(
    ticker: str,
    dates: list[str],
    results_dir: Path,
    recursion_limit: int,
    max_position_pct: float,
    workers: int,
    batch_size: int,
    execution_mode: str,
) -> list[dict]:
    all_results = []
    pending_since_checkpoint = 0
    total = len(dates)

    if workers <= 1:
        print("[Serial mode]")
        for index, trade_date in enumerate(dates, start=1):
            print(f"[{index}/{total}] {ticker} {trade_date} ...", end=" ", flush=True)
            result = run_single_analysis(
                ticker,
                trade_date,
                results_dir,
                recursion_limit,
                max_position_pct,
                write_all_results=False,
                execution_mode=execution_mode,
            )
            all_results.append(result)
            pending_since_checkpoint += 1
            _print_result_status(result)
            if pending_since_checkpoint >= batch_size:
                save_batch_outputs(results_dir, ticker, all_results)
                pending_since_checkpoint = 0
                print(f"  [checkpoint: {index}/{total} tasks saved]")
    else:
        print(f"[Parallel mode: {workers} concurrent workers]")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    run_single_analysis,
                    ticker,
                    trade_date,
                    results_dir,
                    recursion_limit,
                    max_position_pct,
                    False,
                    execution_mode,
                ): trade_date
                for trade_date in dates
            }
            for completed, future in enumerate(as_completed(future_map), start=1):
                trade_date = future_map[future]
                try:
                    result = future.result()
                except Exception:
                    result = {
                        "ticker": ticker,
                        "trade_date": trade_date,
                        "status": "error",
                        "action": "HOLD",
                        "position_pct": 0.0,
                        "position_pct_display": "0.00%",
                        "allocation_posture": "error",
                        "debug_file": "",
                        "error": traceback.format_exc(),
                    }
                all_results.append(result)
                pending_since_checkpoint += 1
                print(f"[{completed}/{total}] {ticker} {trade_date} ...", end=" ", flush=True)
                _print_result_status(result)
                if pending_since_checkpoint >= batch_size:
                    save_batch_outputs(results_dir, ticker, all_results)
                    pending_since_checkpoint = 0
                    print(f"  [checkpoint: {completed}/{total} tasks saved]")

    save_batch_outputs(results_dir, ticker, all_results)
    return sorted(all_results, key=lambda item: item.get("trade_date", ""))


def run_multi_ticker_analysis(
    tickers: list[str],
    date_ranges: dict[str, list[str]],
    results_dir: Path,
    recursion_limit: int,
    max_position_pct: float,
    workers: int,
    batch_size: int,
    execution_mode: str,
) -> list[dict]:
    all_results = []
    total = sum(len(dates) for dates in date_ranges.values())
    pending_since_checkpoint = 0

    print(f"[Multi-ticker parallel mode: {workers} concurrent workers, {total} analyses]")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                run_single_analysis,
                ticker,
                trade_date,
                results_dir,
                recursion_limit,
                max_position_pct,
                False,
                execution_mode,
            ): (ticker, trade_date)
            for ticker in tickers
            for trade_date in date_ranges[ticker]
        }
        for completed, future in enumerate(as_completed(future_map), start=1):
            ticker, trade_date = future_map[future]
            try:
                result = future.result()
            except Exception:
                result = {
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "status": "error",
                    "action": "HOLD",
                    "position_pct": 0.0,
                    "position_pct_display": "0.00%",
                    "allocation_posture": "error",
                    "debug_file": "",
                    "error": traceback.format_exc(),
                }
            all_results.append(result)
            pending_since_checkpoint += 1
            print(f"[{completed}/{total}] {ticker} {trade_date} ...", end=" ", flush=True)
            _print_result_status(result)
            if pending_since_checkpoint >= batch_size:
                save_batch_outputs(results_dir, "multi_ticker", all_results)
                pending_since_checkpoint = 0
                print(f"  [checkpoint: {completed}/{total} tasks saved]")

    save_batch_outputs(results_dir, "multi_ticker", all_results)
    return sorted(all_results, key=lambda item: (item.get("ticker", ""), item.get("trade_date", "")))


def _print_result_status(result: dict) -> None:
    if result.get("error"):
        print(f"ERROR: {str(result['error'])[:160]}")
    else:
        pct = result.get("position_pct_display") or _format_position_pct(result.get("position_pct"))
        posture = result.get("allocation_posture") or "unspecified"
        print(f"OK {result.get('action', 'HOLD')} position={pct} posture={posture}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run four LangGraph analysts followed by the DataEvolver LLM DAG.")
    parser.add_argument("--ticker", default="AMZN", help="Ticker symbol, default AMZN")
    parser.add_argument("--tickers", nargs="+", default=None, help="Run multiple tickers into one combined decisions.csv.")
    parser.add_argument("--date", default=None, help="Single analysis date in YYYY-MM-DD format")
    parser.add_argument("--start-date", default=None, help="Batch start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", default=None, help="Batch end date in YYYY-MM-DD format")
    parser.add_argument("--limit-dates", type=int, default=0, help="Limit batch to the first N trading dates")
    parser.add_argument("--workers", "-w", type=int, default=1, help="Number of concurrent analysis workers")
    parser.add_argument("--batch-size", type=int, default=8, help="Checkpoint results every N completed tasks")
    parser.add_argument("--recursion-limit", type=int, default=80, help="LangGraph recursion limit")
    parser.add_argument("--results-dir", type=Path, default=None, help="Directory for this run's outputs.")
    parser.add_argument(
        "--max-position-pct",
        type=float,
        default=100.0,
        help="Maximum portfolio percentage to allocate to one BUY decision.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print configuration without calling the LLM")
    parser.add_argument(
        "--execution-mode",
        choices=["baseline", "static_ptc", "dynamic_ptc"],
        default="baseline",
        help="DataEvolver execution mode used for ablation experiments.",
    )
    args = parser.parse_args()

    load_env_files()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = args.results_dir or (EXERCISE_ROOT / "analysis_results" / run_timestamp)

    config = load_config()
    profile = config.get("llm_profiles", {}).get("openai", {})
    model = os.environ.get("OPENAI_MODEL") or profile.get("model", "gpt-4o-mini")
    base_url = os.environ.get("OPENAI_BASE_URL") or profile.get("base_url", "https://api.openai.com/v1")
    tickers = [ticker.upper() for ticker in (args.tickers or [args.ticker])]
    batch_mode = bool(args.start_date or args.end_date or args.limit_dates)
    single_date = args.date or "2023-04-10"
    dates = []
    date_ranges: dict[str, list[str]] = {}
    if batch_mode:
        for ticker in tickers:
            ticker_dates = get_trading_dates(ticker, args.start_date, args.end_date, args.limit_dates)
            if not ticker_dates:
                raise SystemExit(f"No trading dates matched the requested range for {ticker}.")
            date_ranges[ticker] = ticker_dates
        dates = date_ranges[tickers[0]]
    else:
        date_ranges = {ticker: [single_date] for ticker in tickers}

    print(f"Tickers: {', '.join(tickers)}")
    if batch_mode:
        counts = ", ".join(f"{ticker}={len(date_ranges[ticker])}" for ticker in tickers)
        print(f"Dates: {dates[0]} to {dates[-1]} ({counts} trading days)")
        print(f"Workers: {max(1, args.workers)}")
    else:
        print(f"Date: {single_date}")
    print(f"Model: {model}")
    print(f"Base URL: {base_url}")
    print(f"Max BUY position pct: {args.max_position_pct:.2f}%")
    print("Workflow: LangGraph four analysts + DataEvolver LLM DAG")
    print(f"Execution mode: {args.execution_mode}")
    print(f"Results dir: {results_dir}")

    if args.dry_run:
        print("Dry run only. No LLM call was made.")
        return

    if len(tickers) > 1:
        results = run_multi_ticker_analysis(
            tickers,
            date_ranges,
            results_dir,
            args.recursion_limit,
            min(100.0, max(0.0, args.max_position_pct)),
            max(1, args.workers),
            max(1, args.batch_size),
            args.execution_mode,
        )
        print(f"\nDone. Total analyses: {len(results)}")
        print(f"Results saved to: {results_dir}")
        print(f"Decisions CSV: {results_dir / 'decisions.csv'}")
        return

    if batch_mode:
        results = run_batch_analysis(
            tickers[0],
            dates,
            results_dir,
            args.recursion_limit,
            min(100.0, max(0.0, args.max_position_pct)),
            max(1, args.workers),
            max(1, args.batch_size),
            args.execution_mode,
        )
        print(f"\nDone. Total analyses: {len(results)}")
        print(f"Results saved to: {results_dir}")
        print(f"Decisions CSV: {results_dir / 'decisions.csv'}")
        return

    result = run_single_analysis(
        tickers[0],
        single_date,
        results_dir,
        args.recursion_limit,
        min(100.0, max(0.0, args.max_position_pct)),
        execution_mode=args.execution_mode,
    )

    print(f"Status: {result['status']}")
    print(f"Debug file: {result['debug_file']}")
    print(f"Reports dir: {results_dir / 'reports'}")

    if result.get("error"):
        print(result["error"])
        raise SystemExit(1)

    for key in [
        "technical_report",
        "fundamental_report",
        "news_report",
        "policy_report",
        "team_discussion_summary",
        "final_decision",
    ]:
        print(f"{key}: {bool(result.get(key))}")


if __name__ == "__main__":
    main()
