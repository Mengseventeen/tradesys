from __future__ import annotations

import json
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from tradesys.workflows.common import clip_text, ensure_local_evidence, fallback_decision, format_final_decision, reports_from_state
from tradesys.workflows.llm_trading_agents import LLMTradingAgentExecutor
from tradesys.workflows.llm_client import invoke_text, require_llm
from tradesys.workflows.trading_operators import (
    REQUIRED_TRADING_OPERATORS,
    build_current_data_profile,
    operator_manual,
    operator_specs_by_name,
)

if TYPE_CHECKING:
    from tradesys.agents.utils.agent_states import AgentState
else:
    AgentState = dict[str, Any]


ACTION_RE = re.compile(r"^\s*\$(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\((.*?)\)\s*(?:#.*)?$", re.MULTILINE)
DEP_RE = re.compile(r"\$(\d+)")


class LLMCompilerPlanner:
    """LLMCompiler-style text planner parsed by regex into a dependency DAG."""

    def __init__(self) -> None:
        self.operator_specs = operator_specs_by_name()

    def build_plan(self, state: AgentState, llm: Any | None = None) -> dict[str, Any]:
        llm = require_llm(llm, "LLMCompiler planner")
        data_profile = build_current_data_profile(state)
        raw_plan_text = self._ask_llm_for_function_plan(state, data_profile, llm)
        nodes, parser_warnings = self._parse_function_plan(raw_plan_text)
        nodes, repair_warnings = self._repair_plan(nodes)
        warnings = parser_warnings + repair_warnings
        join_task = nodes[-1]["id"] if nodes else ""
        return {
            "method": "LLMCompiler",
            "planner": "few_shot_text_function_calling_planner",
            "parser": "regex_extract_dollar_id_function_calls",
            "task_fetching": "dependency_ready_parallel_layers",
            "joiner": "join_agent",
            "ticker": state.get("ticker", ""),
            "trade_date": state.get("trade_date", ""),
            "data_profile": data_profile,
            "operator_manual": operator_manual(),
            "raw_plan_text": raw_plan_text,
            "parser_warnings": warnings,
            "nodes": nodes,
            "edges": [
                {"from": dependency, "to": node["id"], "message": "agent output"}
                for node in nodes
                for dependency in _as_list(node.get("depends_on"))
            ],
            "join_task": join_task,
        }

    def _ask_llm_for_function_plan(self, state: AgentState, data_profile: dict[str, Any], llm: Any) -> str:
        tool_descriptions = "\n".join(
            f"- {item['operator']}({', '.join(item['input_keys'])}) -> {', '.join(item['output_keys'])}: {item['description']}"
            for item in operator_manual()
        )
        few_shot = (
            "Example 1:\n"
            "$1 = read_market_data(raw_evidence, data_profile)\n"
            "$2 = bullish_signal($1)\n"
            "$3 = bearish_signal($1)\n"
            "$4 = disagreement_detection($2, $3, $1)\n"
            "$5 = risk_management($1, $3, $4)\n"
            "$6 = position_sizing($2, $3, $5, $4)\n"
            "$7 = join($6)\n\n"
            "Example 2, maximally parallel where possible:\n"
            "$1 = read_market_data(raw_evidence, data_profile)\n"
            "$2 = bullish_signal($1)\n"
            "$3 = bearish_signal($1)\n"
            "$4 = disagreement_detection($2, $3, $1)\n"
            "$5 = risk_management($1, $3, $4)\n"
            "$6 = position_sizing($2, $3, $5, $4)\n"
            "$7 = join($6)"
        )
        system = (
            "You are the LLMCompiler planner. Produce a function-call plan only, one action per line. "
            "Rules:\n"
            "- Each action MUST have a unique ID, strictly increasing from $1.\n"
            "- Inputs can be constants or outputs from preceding actions.\n"
            "- Use $id to denote the output of a previous action.\n"
            "- Always call join as the last action in the plan.\n"
            "- Ensure the plan maximizes parallelizability.\n"
            "- Use only the listed tools; do not return JSON or markdown."
        )
        user = (
            f"Tools:\n{tool_descriptions}\n\n"
            f"Few-shot examples:\n{few_shot}\n\n"
            f"Ticker: {state.get('ticker')}\nTrade date: {state.get('trade_date')}\n\n"
            f"Current data profile:\n{json.dumps(data_profile, ensure_ascii=False, indent=2, default=str)[:10000]}\n\n"
            f"Reports excerpt:\n{clip_text(' '.join(reports_from_state(state).values()), 3000)}\n\n"
            "Now output the plan."
        )
        return invoke_text(llm, system, user)

    def _parse_function_plan(self, text: str) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        nodes: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        allowed = set(self.operator_specs)
        for match in ACTION_RE.finditer(text):
            numeric_id = int(match.group(1))
            operator = match.group(2)
            args_text = match.group(3)
            task_id = f"${numeric_id}"
            if numeric_id in seen_ids:
                warnings.append(f"duplicate action id ignored: {task_id}")
                continue
            seen_ids.add(numeric_id)
            if operator not in allowed:
                warnings.append(f"unknown tool ignored: {operator}")
                continue
            deps = [f"${dep}" for dep in DEP_RE.findall(args_text) if int(dep) < numeric_id]
            spec = self.operator_specs[operator]
            nodes.append({
                "id": task_id,
                "name": operator,
                "tool": operator,
                "operator": operator,
                "depends_on": _dedupe(deps),
                "input_keys": list(spec.input_keys),
                "output_key": spec.output_keys[0],
                "output_keys": list(spec.output_keys),
                "raw_call": match.group(0).strip(),
                "arguments": [arg.strip() for arg in args_text.split(",") if arg.strip()],
            })
        nodes.sort(key=lambda node: int(str(node["id"]).lstrip("$")))
        if not nodes:
            warnings.append("regex parser found no executable function calls")
        expected = 1
        for node in nodes:
            actual = int(str(node["id"]).lstrip("$"))
            if actual != expected:
                warnings.append(f"action ids are not contiguous at {node['id']}; plan will be normalized by repair")
                break
            expected += 1
        return nodes, warnings

    def _repair_plan(self, nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        operators = [str(node.get("operator")) for node in nodes]
        repaired_ops = [operator for operator in REQUIRED_TRADING_OPERATORS if operator in operators]
        for operator in REQUIRED_TRADING_OPERATORS:
            if operator not in repaired_ops:
                repaired_ops.append(operator)
                warnings.append(f"inserted required operator: {operator}")
        if repaired_ops[-1] != "join":
            repaired_ops = [operator for operator in repaired_ops if operator != "join"] + ["join"]
            warnings.append("moved join to final action")

        repaired_nodes: list[dict[str, Any]] = []
        op_to_id: dict[str, str] = {}
        for index, operator in enumerate(repaired_ops, start=1):
            spec = self.operator_specs[operator]
            task_id = f"${index}"
            op_to_id[operator] = task_id
            repaired_nodes.append({
                "id": task_id,
                "name": operator,
                "tool": operator,
                "operator": operator,
                "depends_on": [],
                "input_keys": list(spec.input_keys),
                "output_key": spec.output_keys[0],
                "output_keys": list(spec.output_keys),
                "description": spec.description,
            })
        for node in repaired_nodes:
            deps = [
                op_to_id[operator]
                for operator in _default_operator_dependencies(str(node["operator"]))
                if operator in op_to_id
            ]
            node["depends_on"] = deps
        return repaired_nodes, warnings


class CompilerPlanValidator:
    def __init__(self) -> None:
        self.operator_specs = operator_specs_by_name()

    def validate(self, plan: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        nodes = plan.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return ["plan has no nodes"]
        ids = [str(node.get("id", "")) for node in nodes if isinstance(node, dict)]
        id_set = set(ids)
        if len(ids) != len(id_set):
            errors.append("plan has duplicate task ids")
        for node in nodes:
            if not isinstance(node, dict):
                errors.append("node is not an object")
                continue
            task_id = str(node.get("id", ""))
            tool = str(node.get("tool", ""))
            if tool not in self.operator_specs:
                errors.append(f"{task_id} uses unknown tool {tool}")
            for dep in _as_list(node.get("depends_on")):
                if dep not in id_set:
                    errors.append(f"{task_id} depends on missing node {dep}")
        if str(plan.get("join_task", "")) != ids[-1]:
            errors.append("join_task is not the final task")
        if str(nodes[-1].get("tool", "")) != "join":
            errors.append("last action is not join")
        execution_order = _topological_order(nodes)
        if len(execution_order) != len(ids):
            errors.append("plan contains a dependency cycle")
        return errors


class LLMCompilerExecutor:
    """Task Fetching Unit plus dependency-ready parallel executor."""

    def __init__(self, max_position_pct: float, llm: Any):
        self.max_position_pct = min(100.0, max(0.0, float(max_position_pct or 100.0)))
        self.executor = LLMTradingAgentExecutor(llm, self.max_position_pct, "llmcompiler_regex_dag")

    def run(self, state: AgentState, plan: dict[str, Any]) -> dict[str, Any]:
        remaining = {str(node["id"]): node for node in plan.get("nodes", [])}
        outputs: dict[str, dict[str, Any]] = {}
        data_store: dict[str, Any] = {
            "raw_evidence": state.get("local_evidence", {}),
            "data_profile": plan.get("data_profile", build_current_data_profile(state)),
        }
        execution_layers: list[list[str]] = []
        task_fetching_events: list[dict[str, Any]] = []
        while remaining:
            ready = [
                task_id
                for task_id, node in remaining.items()
                if all(dep in outputs for dep in _as_list(node.get("depends_on")))
            ]
            if not ready:
                raise ValueError(f"No dependency-ready tasks remain: {sorted(remaining)}")
            execution_layers.append(ready)
            task_fetching_events.append({
                "ready_tasks": ready,
                "waiting_tasks": sorted(set(remaining) - set(ready)),
            })
            with ThreadPoolExecutor(max_workers=max(1, len(ready))) as pool:
                futures = {
                    pool.submit(self._run_node, remaining[task_id], data_store): task_id
                    for task_id in ready
                }
                for future in as_completed(futures):
                    task_id = futures[future]
                    output = future.result()
                    outputs[task_id] = output
                    data_store.update(output.get("operator_output", {}))
            for task_id in ready:
                remaining.pop(task_id, None)

        join_output = outputs.get(str(plan.get("join_task", "")), {})
        return {
            "outputs_by_task": outputs,
            "execution_layers": execution_layers,
            "task_fetching_events": task_fetching_events,
            "topological_order": [task_id for layer in execution_layers for task_id in layer],
            "join_output": join_output,
            "data_store_keys": sorted(data_store.keys()),
        }

    def _run_node(self, node: dict[str, Any], data_store: dict[str, Any]) -> dict[str, Any]:
        operator = str(node.get("tool") or node.get("operator") or "")
        agent_result = self.executor.run_agent(operator, data_store)
        operator_output = agent_result.operator_output
        return {
            "task_id": node.get("id"),
            "task_name": node.get("name"),
            "tool": operator,
            "depends_on": _as_list(node.get("depends_on")),
            "output_key": node.get("output_key"),
            "operator_output": operator_output,
            "quality_evaluation": agent_result.evaluation,
            "attempts": agent_result.attempts,
            "summary": _summarize_operator_output(operator_output),
        }


def run_llmcompiler_workflow(state: AgentState, llm: Any | None = None) -> dict[str, Any]:
    state = ensure_local_evidence(state)
    max_position_pct = state.get("max_position_pct", 100.0)
    try:
        planner = LLMCompilerPlanner()
        plan = planner.build_plan(state, llm=llm)
        validation_errors = CompilerPlanValidator().validate(plan)
        if validation_errors:
            decision = fallback_decision(
                max_position_pct,
                "LLMCompiler plan validation failed: " + "; ".join(validation_errors),
                "llmcompiler",
            )
            return _result_update(state, plan, {"validation_errors": validation_errors}, "invalid", decision)

        execution = LLMCompilerExecutor(max_position_pct, llm).run(state, plan)
        final_decision = _extract_final_decision(execution, max_position_pct)
        return _result_update(state, plan, execution, "ok", final_decision)
    except Exception:
        error = traceback.format_exc()
        decision = fallback_decision(max_position_pct, "LLMCompiler workflow failed.", "llmcompiler")
        update = _result_update(state, {}, {"runtime_error": error}, "error", decision)
        update["error"] = error
        return update


def create_llmcompiler_node(llm: Any | None = None):
    def _node(state: AgentState) -> dict[str, Any]:
        return run_llmcompiler_workflow(state, llm=llm)

    return _node


def _extract_final_decision(execution: dict[str, Any], max_position_pct: float) -> dict[str, Any]:
    join_output = execution.get("join_output", {})
    operator_output = join_output.get("operator_output", {}) if isinstance(join_output, dict) else {}
    decision = operator_output.get("final_decision") if isinstance(operator_output, dict) else None
    if isinstance(decision, dict):
        return decision
    return fallback_decision(max_position_pct, "LLMCompiler join did not produce a final decision.", "llmcompiler")


def _result_update(
    state: AgentState,
    plan: dict[str, Any],
    execution: dict[str, Any],
    status: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    workflow_outputs = {
        "compiler_execution": execution,
        "final_decision_structured": decision,
        "decision_contract": {
            "allowed_actions": ["BUY", "SELL", "HOLD"],
            "position_pct_unit": "percent",
            "max_buy_position_pct": decision.get("max_buy_position_pct", state.get("max_position_pct", 100.0)),
        },
    }
    return {
        "workflow_mode": "llmcompiler",
        "workflow_method": "LLMCompiler",
        "workflow_status": status,
        "workflow_plan": plan,
        "workflow_outputs": workflow_outputs,
        "team_plan": plan,
        "module_outputs": {"llmcompiler": workflow_outputs},
        "generated_skills": operator_manual(),
        "expert_agents": [
            {"name": node.get("id"), "tool": node.get("tool"), "depends_on": node.get("depends_on", [])}
            for node in plan.get("nodes", [])
        ] if plan else [],
        "expert_outputs": execution.get("outputs_by_task", {}) if execution else {},
        "team_discussion_summary": (
            "LLMCompiler generated a regex-parsed function-call DAG, executed dependency-ready tasks "
            "as evaluated LLM agents, and used the join agent for the final decision."
        ),
        "team_summary": {
            "workflow": "llmcompiler",
            "status": status,
            "decision": decision.get("action", "HOLD"),
            "position_pct": decision.get("position_pct", 0.0),
        },
        "final_decision_structured": decision,
        "final_decision": format_final_decision(decision),
    }


def _summarize_operator_output(operator_output: dict[str, Any]) -> str:
    if not isinstance(operator_output, dict) or not operator_output:
        return "LLM agent returned no structured output."
    value = next(iter(operator_output.values()))
    if isinstance(value, dict):
        for key in ("report", "reasoning", "summary", "thesis", "risk_thesis", "sizing_guidance"):
            if value.get(key):
                return clip_text(str(value[key]), 320)
        return clip_text(json.dumps(value, ensure_ascii=False, default=str), 320)
    return clip_text(str(value), 320)


def _default_operator_dependencies(operator: str) -> list[str]:
    if operator == "read_market_data":
        return []
    if operator in {"bullish_signal", "bearish_signal"}:
        return ["read_market_data"]
    if operator == "disagreement_detection":
        return ["bullish_signal", "bearish_signal", "read_market_data"]
    if operator == "risk_management":
        return ["read_market_data", "bearish_signal", "disagreement_detection"]
    if operator == "position_sizing":
        return ["bullish_signal", "bearish_signal", "risk_management", "disagreement_detection"]
    if operator == "join":
        return ["position_sizing"]
    return []


def _topological_order(nodes: list[dict[str, Any]]) -> list[str]:
    node_ids = [str(node.get("id") or "") for node in nodes]
    deps = {str(node.get("id") or ""): set(_as_list(node.get("depends_on"))) for node in nodes}
    order: list[str] = []
    ready = [node_id for node_id in node_ids if node_id and not deps[node_id]]
    while ready:
        node_id = ready.pop(0)
        if node_id in order:
            continue
        order.append(node_id)
        for other_id in node_ids:
            if node_id in deps.get(other_id, set()):
                deps[other_id].remove(node_id)
                if not deps[other_id]:
                    ready.append(other_id)
    return order


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    text = str(value)
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
