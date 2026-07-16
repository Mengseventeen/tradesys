from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
DEFAULT_TICKERS = ["AMZN", "MSFT", "NFLX", "TSLA"]
ALL_MODES = ["baseline", "static_ptc", "dynamic_ptc"]


def run_command(command: list[str], stdout_path: Path, stderr_path: Path) -> float:
    started = time.perf_counter()
    with open(stdout_path, "w", encoding="utf-8") as stdout, open(stderr_path, "w", encoding="utf-8") as stderr:
        completed = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}. "
            f"See {stderr_path}."
        )
    return elapsed


def run_mode(args: argparse.Namespace, mode: str, root: Path) -> dict[str, Any]:
    result_dir = root / mode
    result_dir.mkdir(parents=True, exist_ok=True)
    analysis_command = [
        sys.executable,
        "-u",
        str(ROOT / "run_analysis.py"),
        "--tickers",
        *args.tickers,
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--workers",
        str(args.workers),
        "--batch-size",
        str(args.batch_size),
        "--max-position-pct",
        str(args.max_position_pct),
        "--execution-mode",
        mode,
        "--results-dir",
        str(result_dir),
    ]
    analysis_seconds = run_command(
        analysis_command,
        result_dir / "stdout.log",
        result_dir / "stderr.log",
    )

    evaluation_seconds = 0.0
    if not args.skip_evaluation:
        evaluation_command = [
            sys.executable,
            str(ROOT / "evaluate_position_pct_replay.py"),
            "--decisions",
            str(result_dir / "decisions.csv"),
            "--execution",
            "next_day_open",
            "--final-liquidation",
            "--output-dir",
            str(result_dir / "performance_next_day_open"),
        ]
        evaluation_seconds = run_command(
            evaluation_command,
            result_dir / "evaluation_stdout.log",
            result_dir / "evaluation_stderr.log",
        )
    return summarize_mode(result_dir, mode, analysis_seconds, evaluation_seconds)


def summarize_mode(
    result_dir: Path,
    mode: str,
    analysis_seconds: float,
    evaluation_seconds: float,
) -> dict[str, Any]:
    decisions = _read_csv(result_dir / "decisions.csv")
    debug_files = sorted((result_dir / "debug_runs").glob("*.json"))
    tool_calls = 0
    skipped_calls = 0
    execution_layers = 0
    strategies: dict[str, int] = {}

    for path in debug_files:
        debug = json.loads(path.read_text(encoding="utf-8"))
        execution = debug.get("workflow", {}).get("workflow_outputs", {}).get("dag_execution", {})
        call_trace = execution.get("call_trace")
        if isinstance(call_trace, list):
            tool_calls += sum(1 for item in call_trace if item.get("kind") == "tool_call")
            skipped_calls += sum(1 for item in call_trace if item.get("kind") == "constant")
        else:
            outputs = execution.get("node_outputs", {})
            tool_calls += len(outputs) if isinstance(outputs, dict) else 0
        layers = execution.get("execution_layers")
        if isinstance(layers, list):
            execution_layers += len(layers)
        elif execution.get("execution_order"):
            execution_layers += len(execution.get("execution_order", []))
        strategy = str(execution.get("strategy") or execution.get("mode") or "baseline")
        strategies[strategy] = strategies.get(strategy, 0) + 1

    ok_rows = [row for row in decisions if row.get("status") == "ok" and not row.get("error")]
    action_counts = {
        action: sum(1 for row in ok_rows if str(row.get("action", "")).upper() == action)
        for action in ["BUY", "SELL", "HOLD"]
    }
    metrics = _read_csv(result_dir / "performance_next_day_open" / "position_pct_metrics.csv")
    average_metrics = next((row for row in metrics if row.get("ticker") == "Average"), metrics[0] if metrics else {})
    count = len(debug_files) or 1
    return {
        "mode": mode,
        "result_dir": str(result_dir),
        "analysis_seconds": round(analysis_seconds, 3),
        "evaluation_seconds": round(evaluation_seconds, 3),
        "decision_count": len(decisions),
        "ok_count": len(ok_rows),
        "error_count": len(decisions) - len(ok_rows),
        "action_counts": action_counts,
        "average_tool_calls": round(tool_calls / count, 3),
        "average_skipped_calls": round(skipped_calls / count, 3),
        "average_execution_layers": round(execution_layers / count, 3),
        "routing_strategies": strategies,
        "SPR": _number(average_metrics.get("SPR")),
        "CR": _number(average_metrics.get("CR")),
        "MDD": _number(average_metrics.get("MDD")),
        "AV": _number(average_metrics.get("AV")),
    }


def save_summary(root: Path, summaries: list[dict[str, Any]]) -> None:
    (root / "ablation_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fields = [
        "mode",
        "analysis_seconds",
        "evaluation_seconds",
        "decision_count",
        "ok_count",
        "error_count",
        "average_tool_calls",
        "average_skipped_calls",
        "average_execution_layers",
        "SPR",
        "CR",
        "MDD",
        "AV",
    ]
    with open(root / "ablation_summary.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({field: summary.get(field, "") for field in fields})


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run baseline, static PTC, and dynamic PTC ablations.")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--start-date", default="2022-10-06")
    parser.add_argument("--end-date", default="2023-04-10")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-position-pct", type=float, default=100.0)
    parser.add_argument("--modes", nargs="+", choices=ALL_MODES, default=ALL_MODES)
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--results-dir", type=Path, default=None)
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    root = args.results_dir or ROOT / "analysis_results" / f"ptc_ablation_{timestamp}"
    root.mkdir(parents=True, exist_ok=True)
    summaries = []
    for mode in args.modes:
        print(f"Running {mode}...", flush=True)
        summary = run_mode(args, mode, root)
        summaries.append(summary)
        save_summary(root, summaries)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"Ablation results saved to {root}")


if __name__ == "__main__":
    main()
