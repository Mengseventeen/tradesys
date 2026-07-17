from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from tradesys.workflows.trading_operators import operator_specs_by_name


PTC_PROGRAM_VERSION = "ptc-ir-v1"
ALLOWED_INSTRUCTION_KINDS = {"tool_call", "constant"}


class PTCProgramError(ValueError):
    pass


class PTCProgramCompiler:
    """Compile a DataEvolver DAG into a restricted, auditable tool-call program."""

    def __init__(self) -> None:
        self.specs = operator_specs_by_name()

    def compile_static(self, plan: dict[str, Any]) -> dict[str, Any]:
        instructions = []
        for node in plan.get("nodes", []):
            operator = str(node.get("operator") or "")
            spec = self.specs[operator]
            instructions.append({
                "id": str(node.get("step_id") or node.get("id")),
                "kind": "tool_call",
                "operator": operator,
                "depends_on": [str(item) for item in node.get("depends_on", [])],
                "input_keys": list(spec.input_keys),
                "output_keys": list(spec.output_keys),
            })
        return self._program("static_ptc", "full_seven_operator_dag", instructions)

    def compile_dynamic(
        self,
        plan: dict[str, Any],
        data_profile: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = select_market_strategy(data_profile)
        by_operator = {
            str(node.get("operator")): node
            for node in plan.get("nodes", [])
        }

        instructions: list[dict[str, Any]] = []
        for operator in [
            "read_market_data",
            "bullish_signal",
            "bearish_signal",
            "disagreement_detection",
            "risk_management",
            "position_sizing",
            "join",
        ]:
            node = by_operator[operator]
            node_id = str(node.get("step_id") or node.get("id"))
            spec = self.specs[operator]
            kind = "tool_call"
            value: dict[str, Any] | None = None

            if operator == "bullish_signal" and not strategy["run_bullish_agent"]:
                kind = "constant"
                value = {"bullish_view": _skipped_bullish_view(strategy)}
            elif operator == "bearish_signal" and not strategy["run_bearish_agent"]:
                kind = "constant"
                value = {"bearish_view": _skipped_bearish_view(strategy)}
            elif operator == "disagreement_detection" and not strategy["run_disagreement_agent"]:
                kind = "constant"
                value = {"disagreement_report": {
                    "report": "The disagreement agent was skipped because the regime selected one directional branch.",
                    "has_material_disagreement": False,
                    "conflicts": [],
                    "resolution_guidance": "Use the selected branch with the normal risk controls.",
                    "ptc_skipped": True,
                }}

            instruction = {
                "id": node_id,
                "kind": kind,
                "operator": operator,
                "depends_on": [str(item) for item in node.get("depends_on", [])],
                "input_keys": list(spec.input_keys),
                "output_keys": list(spec.output_keys),
            }
            if value is not None:
                instruction["value"] = value
            instructions.append(instruction)

        return self._program("dynamic_ptc", strategy["name"], instructions, strategy)

    def _program(
        self,
        mode: str,
        strategy: str,
        instructions: list[dict[str, Any]],
        routing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        program = {
            "version": PTC_PROGRAM_VERSION,
            "mode": mode,
            "strategy": strategy,
            "instructions": instructions,
            "routing": routing or {},
        }
        validation = validate_ptc_program(program, self.specs)
        program["validation"] = validation
        if not validation["is_valid"]:
            raise PTCProgramError("; ".join(validation["issues"]))
        program["source"] = render_ptc_program(program)
        return program


class PTCProgramRuntime:
    """Execute only validated PTC IR; arbitrary Python is never evaluated."""

    def __init__(self, agent_executor: Any, max_parallel_tools: int = 4) -> None:
        self.agent_executor = agent_executor
        self.max_parallel_tools = max(1, int(max_parallel_tools))

    def execute(
        self,
        program: dict[str, Any],
        initial_data: dict[str, Any],
    ) -> dict[str, Any]:
        validation = validate_ptc_program(program, operator_specs_by_name())
        if not validation["is_valid"]:
            raise PTCProgramError("; ".join(validation["issues"]))

        remaining = {
            str(item["id"]): deepcopy(item)
            for item in program.get("instructions", [])
        }
        completed: set[str] = set()
        data_store = deepcopy(initial_data)
        node_outputs: dict[str, Any] = {}
        execution_layers: list[list[str]] = []
        call_trace: list[dict[str, Any]] = []

        while remaining:
            ready = [
                instruction_id
                for instruction_id, instruction in remaining.items()
                if all(str(dep) in completed for dep in instruction.get("depends_on", []))
            ]
            if not ready:
                raise PTCProgramError(f"No ready instructions remain: {sorted(remaining)}")
            execution_layers.append(ready)
            snapshot = deepcopy(data_store)

            with ThreadPoolExecutor(max_workers=min(self.max_parallel_tools, len(ready))) as pool:
                futures = {
                    pool.submit(self._execute_instruction, remaining[item_id], snapshot): item_id
                    for item_id in ready
                }
                layer_results = {
                    item_id: future.result()
                    for future, item_id in ((future, futures[future]) for future in as_completed(futures))
                }

            for item_id in ready:
                result = layer_results[item_id]
                for key, value in result["output"].items():
                    if key in data_store:
                        raise PTCProgramError(f"Output key collision: {key}")
                    data_store[key] = value
                node_outputs[item_id] = result["node_output"]
                call_trace.append(result["trace"])
                completed.add(item_id)
                remaining.pop(item_id)

        return {
            "stage": "ptc_program_execution",
            "mode": program.get("mode"),
            "strategy": program.get("strategy"),
            "program": program,
            "program_source": program.get("source", ""),
            "program_validation": validation,
            "execution_layers": execution_layers,
            "execution_order": [item for layer in execution_layers for item in layer],
            "call_trace": call_trace,
            "node_outputs": node_outputs,
            "data_store_keys": sorted(data_store),
            "final_decision_structured": data_store.get("final_decision", {}),
        }

    def _execute_instruction(
        self,
        instruction: dict[str, Any],
        data_store: dict[str, Any],
    ) -> dict[str, Any]:
        operator = str(instruction["operator"])
        if instruction["kind"] == "constant":
            output = deepcopy(instruction["value"])
            node_output = {
                "operator": operator,
                "output": output,
                "quality_evaluation": {
                    "passed": True,
                    "score": 1.0,
                    "evaluator": "ptc_router",
                    "feedback": "The market-regime router safely substituted this branch.",
                },
                "attempts": [],
                "ptc_skipped": True,
            }
            trace = {"instruction": instruction["id"], "operator": operator, "kind": "constant"}
            return {"output": output, "node_output": node_output, "trace": trace}

        agent_result = self.agent_executor.run_agent(operator, data_store)
        output = agent_result.operator_output
        node_output = {
            "operator": operator,
            "output": output,
            "quality_evaluation": agent_result.evaluation,
            "attempts": agent_result.attempts,
            "ptc_skipped": False,
        }
        trace = {
            "instruction": instruction["id"],
            "operator": operator,
            "kind": "tool_call",
            "input_keys": list(instruction.get("input_keys", [])),
            "output_keys": sorted(output),
        }
        return {"output": output, "node_output": node_output, "trace": trace}


def validate_ptc_program(
    program: dict[str, Any],
    specs: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    if program.get("version") != PTC_PROGRAM_VERSION:
        issues.append("Unsupported PTC program version.")
    instructions = program.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        return {"is_valid": False, "issues": ["Program has no instructions."]}

    ids = [str(item.get("id", "")) for item in instructions if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        issues.append("Instruction ids must be unique.")
    id_set = set(ids)
    produced = {"raw_evidence", "data_profile"}
    pending = {str(item["id"]): item for item in instructions if isinstance(item, dict) and item.get("id")}

    while pending:
        ready = [
            item_id
            for item_id, item in pending.items()
            if all(str(dep) not in pending for dep in item.get("depends_on", []))
        ]
        if not ready:
            issues.append("Program has a dependency cycle.")
            break
        for item_id in ready:
            item = pending.pop(item_id)
            kind = str(item.get("kind", ""))
            operator = str(item.get("operator", ""))
            if kind not in ALLOWED_INSTRUCTION_KINDS:
                issues.append(f"{item_id} has forbidden instruction kind {kind}.")
            if operator not in specs:
                issues.append(f"{item_id} uses unknown operator {operator}.")
                continue
            for dep in item.get("depends_on", []):
                if str(dep) not in id_set:
                    issues.append(f"{item_id} depends on missing instruction {dep}.")
            spec = specs[operator]
            missing = [key for key in spec.input_keys if key not in produced]
            if missing:
                issues.append(f"{item_id}/{operator} missing inputs: {', '.join(missing)}.")
            if kind == "constant":
                value = item.get("value")
                if not isinstance(value, dict) or any(key not in value for key in spec.output_keys):
                    issues.append(f"{item_id}/{operator} has an invalid constant output.")
            produced.update(spec.output_keys)
    if "final_decision" not in produced:
        issues.append("Program does not produce final_decision.")
    return {"is_valid": not issues, "issues": issues, "produced_keys": sorted(produced)}


def select_market_strategy(data_profile: dict[str, Any]) -> dict[str, Any]:
    technical = data_profile.get("technical", {})
    fundamental = data_profile.get("fundamental", {})
    news = data_profile.get("news", {})
    policy = data_profile.get("policy", {})
    volatility = _float(technical.get("volatility_pct"))
    drawdown = _float(technical.get("drawdown60_pct"))
    sell_signal = bool(technical.get("sell_signal"))
    buy_signal = bool(technical.get("buy_signal"))
    restrictive = bool(policy.get("restrictive_policy"))

    risk_off = sell_signal or volatility >= 4.0 or drawdown <= -15.0
    clean_bullish = (
        buy_signal
        and not risk_off
        and fundamental.get("stance") != "bearish"
        and news.get("stance") != "bearish"
        and not restrictive
    )
    if risk_off:
        name = "risk_off_bearish_focus"
        run_bullish = False
        run_bearish = True
    elif clean_bullish:
        name = "clean_bullish_focus"
        run_bullish = True
        run_bearish = False
    else:
        name = "mixed_evidence_dual_branch"
        run_bullish = True
        run_bearish = True
    return {
        "name": name,
        "run_bullish_agent": run_bullish,
        "run_bearish_agent": run_bearish,
        "run_disagreement_agent": run_bullish and run_bearish,
        "signals": {
            "buy_signal": buy_signal,
            "sell_signal": sell_signal,
            "volatility_pct": volatility,
            "drawdown60_pct": drawdown,
            "restrictive_policy": restrictive,
        },
    }


def render_ptc_program(program: dict[str, Any]) -> str:
    lines = [f"# {program.get('version')} mode={program.get('mode')} strategy={program.get('strategy')}"]
    for item in program.get("instructions", []):
        output = ", ".join(item.get("output_keys", []))
        deps = ", ".join(item.get("depends_on", [])) or "root"
        if item.get("kind") == "constant":
            lines.append(f"{output} = constant_for('{item.get('operator')}')  # depends: {deps}")
        else:
            inputs = ", ".join(item.get("input_keys", []))
            lines.append(f"{output} = call_tool('{item.get('operator')}', {inputs})  # depends: {deps}")
    return "\n".join(lines)


def _skipped_bullish_view(strategy: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": "The bullish agent was skipped by the risk-off PTC route.",
        "thesis": "no actionable bullish thesis",
        "supporting_evidence": [],
        "cautions": ["The market regime requires bearish and risk analysis first."],
        "confidence": 0.0,
        "action_bias": "HOLD",
        "ptc_skipped": True,
        "routing_strategy": strategy["name"],
    }


def _skipped_bearish_view(strategy: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": "The bearish agent was skipped by the clean-bullish PTC route.",
        "risk_thesis": "no actionable bearish thesis",
        "risk_evidence": [],
        "offsets": ["The current route passed its bullish and risk filters."],
        "confidence": 0.0,
        "action_bias": "HOLD",
        "ptc_skipped": True,
        "routing_strategy": strategy["name"],
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
