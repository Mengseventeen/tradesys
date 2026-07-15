from __future__ import annotations

import json
import os
import traceback
from typing import TYPE_CHECKING, Any

from tradesys.workflows.common import (
    clip_text,
    decision_from_instruction,
    ensure_local_evidence,
    fallback_decision,
    format_final_decision,
)
from tradesys.workflows.llm_trading_agents import LLMTradingAgentExecutor
from tradesys.workflows.llm_client import invoke_json, require_llm
from tradesys.workflows.trading_operators import (
    REQUIRED_TRADING_OPERATORS,
    TRADING_TEMPLATES,
    build_current_data_profile,
    field_info_from_profile,
    operator_manual,
    operator_specs_by_name,
)

if TYPE_CHECKING:
    from tradesys.agents.utils.agent_states import AgentState
else:
    AgentState = dict[str, Any]


class DataEvolverWorkflow:
    """DataEvolver-style three-stage DAG construction for trading decisions."""

    def __init__(self, max_position_pct: float, llm: Any | None = None):
        self.max_position_pct = min(100.0, max(0.0, float(max_position_pct or 100.0)))
        self.operator_specs = operator_specs_by_name()
        self.use_llm_dag = _env_truthy("TRADESYS_DATAEVOLVER_USE_LLM_DAG")
        self.llm = require_llm(llm, "DataEvolver") if self.use_llm_dag else llm
        self.executor = (
            LLMTradingAgentExecutor(self.llm, self.max_position_pct, "dataevolver_abc_dag")
            if self.use_llm_dag
            else None
        )

    def run(self, state: AgentState) -> dict[str, Any]:
        state = ensure_local_evidence(state)
        try:
            data_profile = build_current_data_profile(state)
            if not self.use_llm_dag:
                return self._run_signal_only_dag(state, data_profile)

            understanding_result = self._data_understanding_stage(state, data_profile)
            blueprint = self._free_fitting_stage(understanding_result)
            template_plan = self._template_combination_stage(blueprint, understanding_result)
            logical_plan = self._constrained_search_stage(template_plan, blueprint, understanding_result)
            validation = self._validate_dag(logical_plan)
            if not validation["is_valid"]:
                decision = fallback_decision(
                    self.max_position_pct,
                    "DataEvolver generated an invalid DAG: " + "; ".join(validation["issues"]),
                    "dataevolver",
                )
                return self._result_update(
                    state,
                    data_profile,
                    understanding_result,
                    blueprint,
                    template_plan,
                    logical_plan,
                    validation,
                    {},
                    "invalid",
                    decision,
                )

            execution = self._execute_dag(state, data_profile, logical_plan, validation["execution_order"])
            decision = execution["final_decision_structured"]
            return self._result_update(
                state,
                data_profile,
                understanding_result,
                blueprint,
                template_plan,
                logical_plan,
                validation,
                execution,
                "ok",
                decision,
            )
        except Exception:
            error = traceback.format_exc()
            decision = fallback_decision(self.max_position_pct, "DataEvolver runtime failed.", "dataevolver")
            update = self._result_update(state, {}, {}, {}, {}, {}, {}, {"runtime_error": error}, "error", decision)
            update["error"] = error
            return update

    def _data_understanding_stage(self, state: AgentState, data_profile: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are DataEvolver's data-understanding module for a stock-trading DAG generator. "
            "Inspect the current raw evidence and output data format, field differences, and optimization goals. "
            "This project has no seed data; use only the supplied current raw evidence."
        )
        user = (
            f"Ticker: {state.get('ticker')}\nTrade date: {state.get('trade_date')}\n\n"
            f"Current evidence profile:\n{_json(data_profile, 12000)}\n\n"
            "Return JSON with this schema:\n"
            "{\n"
            '  "data_format": {"raw_blocks": [], "raw_fields": {}},\n'
            '  "data_differences": ["differences across technical/fundamental/news/policy evidence"],\n'
            '  "optimization_goals": ["goal 1", "goal 2"],\n'
            '  "field_info": {"raw_fields": {}, "seed_fields": [], "new_fields": []},\n'
            '  "reasoning": "brief explanation"\n'
            "}"
        )
        parsed = invoke_json(self.llm, system, user)
        if not parsed:
            parsed = {}
        parsed.setdefault("data_format", {"raw_blocks": data_profile.get("raw_blocks", []), "raw_fields": data_profile.get("raw_fields", {})})
        parsed.setdefault("data_differences", ["Technical, fundamental, news, and policy fields have different units and stances."])
        parsed.setdefault("optimization_goals", ["Generate a valid trading DAG", "Produce BUY/SELL/HOLD with position_pct"])
        parsed.setdefault("field_info", field_info_from_profile(data_profile))
        parsed["stage"] = "data_understanding"
        return parsed

    def _free_fitting_stage(self, understanding_result: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are DataEvolver free-fitting stage A. Choose the global optimization direction "
            "before selecting templates or concrete operators."
        )
        user = (
            f"Understanding result:\n{_json(understanding_result, 12000)}\n\n"
            "Return JSON exactly matching this schema:\n"
            "{\n"
            '  "global_optimization_direction": "overall direction",\n'
            '  "key_improvements": ["improvement 1", "improvement 2"],\n'
            '  "transformation_strategies": ["strategy 1", "strategy 2"],\n'
            '  "quality_focus": ["focus 1", "focus 2"]\n'
            "}"
        )
        parsed = invoke_json(self.llm, system, user)
        if not parsed:
            raise ValueError("DataEvolver free-fitting stage returned empty JSON.")
        parsed["stage"] = "free_fitting_stage"
        return parsed

    def _template_combination_stage(
        self,
        blueprint: dict[str, Any],
        understanding_result: dict[str, Any],
    ) -> dict[str, Any]:
        system = (
            "You are DataEvolver template-combination stage B. Select abstract pipeline templates "
            "from the available template library, then output a pipeline sketch."
        )
        user = (
            f"Blueprint:\n{_json(blueprint, 10000)}\n\n"
            f"Understanding result:\n{_json(understanding_result, 10000)}\n\n"
            f"Available templates:\n{_json(TRADING_TEMPLATES, 10000)}\n\n"
            "Return JSON with this schema:\n"
            "{\n"
            '  "selected_templates": ["signal_decomposition"],\n'
            '  "pipeline_sketch": {\n'
            '    "steps": [\n'
            '      {"step_id":"step_1", "template_name":"signal_decomposition", "functional_description":"read current evidence"},\n'
            '      {"step_id":"step_2", "template_name":"signal_decomposition", "functional_description":"build bullish/bearish views"},\n'
            '      {"step_id":"step_3", "template_name":"position_construction", "functional_description":"size final position"}\n'
            "    ]\n"
            "  }\n"
            "}"
        )
        parsed = invoke_json(self.llm, system, user)
        if not parsed:
            raise ValueError("DataEvolver template-combination stage returned empty JSON.")
        parsed.setdefault("selected_templates", [])
        parsed.setdefault("pipeline_sketch", {"steps": []})
        parsed["stage"] = "template_combination_stage"
        return parsed

    def _constrained_search_stage(
        self,
        template_plan: dict[str, Any],
        blueprint: dict[str, Any],
        understanding_result: dict[str, Any],
    ) -> dict[str, Any]:
        field_info = understanding_result.get("field_info") or {}
        system = (
            "You are DataEvolver constrained-search stage C. Arrange concrete executable operators "
            "into a valid DAG. Use only operators from the manual. Do not invent seed fields."
        )
        user = (
            "Inputs for constrained search:\n"
            f"1. Abstract steps:\n{_json(template_plan.get('pipeline_sketch', {}).get('steps', []), 10000)}\n\n"
            f"2. Optimization blueprint:\n{_json(blueprint, 10000)}\n\n"
            f"3. Operator manual:\n{_json(operator_manual(), 12000)}\n\n"
            f"4. Field information:\n{_json(field_info, 10000)}\n\n"
            "5. Format requirement: return final_pipeline only; step_id values must be unique and ordered.\n"
            "6. Quality standards: the graph must be acyclic, must use current evidence only, must include "
            "risk management, bullish/bearish analysis, position sizing, disagreement detection, and must end with join. "
            "Each operator will run as an LLM agent that generates a fresh structured node output; "
            "the join operator is the final decision agent.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "final_pipeline": [\n'
            '    {"step_id":"step_1","operator":"read_market_data","input_keys":["raw_evidence","data_profile"],"output_keys":["market_context"],"depends_on":[],"rationale":"..."},\n'
            '    {"step_id":"step_2","operator":"bullish_signal","input_keys":["market_context"],"output_keys":["bullish_view"],"depends_on":["step_1"],"rationale":"..."},\n'
            '    {"step_id":"step_7","operator":"join","input_keys":["trade_instruction"],"output_keys":["final_decision"],"depends_on":["step_6"],"rationale":"..."}\n'
            "  ]\n"
            "}"
        )
        constrained = invoke_json(self.llm, system, user)
        nodes = self._normalize_final_pipeline(constrained)
        return {
            "stage": "constrained_search_stage",
            "method": "DataEvolver",
            "mode": "understanding_freefit_template_constrained_search",
            "final_pipeline": nodes,
            "nodes": nodes,
            "edges": [
                {"from": dep, "to": node["step_id"], "message": "agent output"}
                for node in nodes
                for dep in node.get("depends_on", [])
            ],
            "execution_order": [node["step_id"] for node in nodes],
            "llm_constrained_search": constrained,
        }

    def _normalize_final_pipeline(self, constrained: dict[str, Any]) -> list[dict[str, Any]]:
        raw_nodes = constrained.get("final_pipeline") if isinstance(constrained, dict) else []
        if not isinstance(raw_nodes, list):
            raw_nodes = []

        selected: list[str] = []
        rationale_by_operator: dict[str, str] = {}
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            operator = str(raw.get("operator") or "")
            if operator in self.operator_specs and operator not in selected:
                selected.append(operator)
                rationale_by_operator[operator] = str(raw.get("rationale") or raw.get("functional_description") or "")

        ordered = [operator for operator in REQUIRED_TRADING_OPERATORS if operator in selected]
        for operator in REQUIRED_TRADING_OPERATORS:
            if operator not in ordered:
                ordered.append(operator)

        nodes: list[dict[str, Any]] = []
        operator_to_step: dict[str, str] = {}
        for index, operator in enumerate(ordered, start=1):
            step_id = f"step_{index}"
            operator_to_step[operator] = step_id
            spec = self.operator_specs[operator]
            nodes.append({
                "step_id": step_id,
                "id": step_id,
                "operator": operator,
                "input_keys": list(spec.input_keys),
                "output_keys": list(spec.output_keys),
                "depends_on": [],
                "rationale": rationale_by_operator.get(operator, ""),
            })
        for node in nodes:
            deps = [
                operator_to_step[operator]
                for operator in _default_operator_dependencies(node["operator"])
                if operator in operator_to_step
            ]
            node["depends_on"] = deps
        return nodes

    def _validate_dag(self, plan: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []
        nodes = plan.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            return {"is_valid": False, "issues": ["DAG has no nodes."], "execution_order": [], "available_keys": []}

        node_by_id: dict[str, dict[str, Any]] = {}
        operators = set()
        for node in nodes:
            node_id = str(node.get("step_id") or node.get("id") or "")
            operator = str(node.get("operator") or "")
            if not node_id:
                issues.append("A node is missing step_id.")
                continue
            if node_id in node_by_id:
                issues.append(f"Duplicate step_id: {node_id}.")
            if operator not in self.operator_specs:
                issues.append(f"Unknown operator: {operator}.")
            node_by_id[node_id] = node
            operators.add(operator)

        for node in nodes:
            node_id = str(node.get("step_id") or node.get("id") or "")
            for dep in _as_list(node.get("depends_on")):
                if dep not in node_by_id:
                    issues.append(f"{node_id} depends on missing node {dep}.")

        execution_order = _topological_order(nodes)
        if len(execution_order) != len(node_by_id):
            issues.append("DAG contains a cycle or unresolved dependency.")

        available_keys = {"raw_evidence", "data_profile"}
        for node_id in execution_order:
            node = node_by_id[node_id]
            operator = str(node.get("operator") or "")
            spec = self.operator_specs.get(operator)
            if not spec:
                continue
            missing = [key for key in spec.input_keys if key not in available_keys]
            if missing:
                issues.append(f"{node_id}/{operator} missing input keys: {', '.join(missing)}.")
            available_keys.update(spec.output_keys)

        for required in REQUIRED_TRADING_OPERATORS:
            if required not in operators:
                issues.append(f"Required operator missing: {required}.")
        if "final_decision" not in available_keys:
            issues.append("DAG does not produce final_decision.")

        return {
            "is_valid": not issues,
            "issues": issues,
            "execution_order": execution_order,
            "available_keys": sorted(available_keys),
        }

    def _execute_dag(
        self,
        state: AgentState,
        data_profile: dict[str, Any],
        plan: dict[str, Any],
        execution_order: list[str],
    ) -> dict[str, Any]:
        if self.executor is None:
            raise RuntimeError("DataEvolver LLM DAG executor is disabled in signal-only mode.")

        node_by_id = {str(node.get("step_id") or node.get("id")): node for node in plan.get("nodes", [])}
        data_store: dict[str, Any] = {
            "raw_evidence": state.get("local_evidence", {}),
            "data_profile": data_profile,
        }
        node_outputs: dict[str, Any] = {}
        for node_id in execution_order:
            node = node_by_id[node_id]
            agent_result = self.executor.run_agent(str(node["operator"]), data_store)
            output = agent_result.operator_output
            data_store.update(output)
            node_outputs[node_id] = {
                "operator": node["operator"],
                "output": output,
                "quality_evaluation": agent_result.evaluation,
                "attempts": agent_result.attempts,
            }

        final_decision = self._final_decision_from_join(data_store)
        data_store["final_decision_structured"] = final_decision
        return {
            "stage": "dag_execution",
            "mode": "llm_agent_nodes_with_evaluate_and_revise",
            "execution_order": execution_order,
            "node_outputs": node_outputs,
            "data_store_keys": sorted(data_store.keys()),
            "final_decision_structured": final_decision,
        }

    def _final_decision_from_join(self, data_store: dict[str, Any]) -> dict[str, Any]:
        final_decision = data_store.get("final_decision")
        if not isinstance(final_decision, dict):
            return fallback_decision(self.max_position_pct, "DataEvolver join agent did not produce final_decision.", "dataevolver")
        decision = decision_from_instruction(final_decision, self.max_position_pct, "dataevolver_join_agent")
        decision["llm_decision_mode"] = "dag_join_agent"
        return decision

    def _run_signal_only_dag(self, state: AgentState, data_profile: dict[str, Any]) -> dict[str, Any]:
        technical = self._technical_signal(state)
        decision = self._decision_from_technical_signal(state, technical)
        understanding_result = {
            "stage": "data_understanding",
            "data_format": {
                "raw_blocks": data_profile.get("raw_blocks", []),
                "raw_fields": data_profile.get("raw_fields", {}),
            },
            "data_differences": [
                "Technical fields provide directly testable buy_signal/sell_signal flags.",
                "Fundamental, news, and policy fields are retained as context but do not size the trade.",
            ],
            "optimization_goals": [
                "Emit a clean BUY/SELL/HOLD trading signal.",
                "Prefer positive per-ticker replay over verbose position construction.",
                "Avoid exposing portfolio position sizing in the final answer.",
            ],
            "field_info": field_info_from_profile(data_profile),
            "reasoning": "Signal-only DataEvolver uses the local technical guard as the final trading contract.",
        }
        blueprint = {
            "stage": "free_fitting_stage",
            "global_optimization_direction": "profit_guarded_signal_only_trading",
            "key_improvements": [
                "Treat sell_signal as a mandatory exit.",
                "Treat buy_signal as the only allowed entry.",
                "Emit HOLD whenever neither guard is active.",
            ],
            "transformation_strategies": [
                "Convert local evidence into explicit signal-agent outputs.",
                "Keep position_pct only as a hidden compatibility field for existing evaluators.",
            ],
            "quality_focus": [
                "Every final signal must match the technical guard.",
                "The final text must not depend on position sizing.",
            ],
        }
        template_plan = {
            "stage": "template_combination_stage",
            "selected_templates": ["signal_decomposition", "risk_first_signal_gate", "signal_only_join"],
            "pipeline_sketch": {
                "steps": [
                    {"step_id": "step_1", "template_name": "signal_decomposition", "functional_description": "read current evidence"},
                    {"step_id": "step_2", "template_name": "risk_first_signal_gate", "functional_description": "apply sell-before-buy guard"},
                    {"step_id": "step_3", "template_name": "signal_only_join", "functional_description": "emit final trading signal"},
                ]
            },
        }
        logical_plan = self._signal_only_plan()
        validation = {
            "is_valid": True,
            "issues": [],
            "execution_order": [node["step_id"] for node in logical_plan["nodes"]],
            "available_keys": ["raw_evidence", "data_profile", "technical_signal", "risk_gate", "final_decision"],
        }
        execution = self._signal_only_execution(state, data_profile, technical, decision, validation["execution_order"])
        return self._result_update(
            state,
            data_profile,
            understanding_result,
            blueprint,
            template_plan,
            logical_plan,
            validation,
            execution,
            "ok",
            decision,
        )

    def _signal_only_plan(self) -> dict[str, Any]:
        nodes = [
            {
                "step_id": "step_1",
                "id": "step_1",
                "operator": "read_market_data",
                "input_keys": ["raw_evidence", "data_profile"],
                "output_keys": ["market_context"],
                "depends_on": [],
                "rationale": "Expose the local market evidence to downstream signal agents.",
            },
            {
                "step_id": "step_2",
                "id": "step_2",
                "operator": "risk_management",
                "input_keys": ["market_context"],
                "output_keys": ["risk_gate"],
                "depends_on": ["step_1"],
                "rationale": "Give sell_signal priority so weak trend states are exited before any entry.",
            },
            {
                "step_id": "step_3",
                "id": "step_3",
                "operator": "join",
                "input_keys": ["risk_gate"],
                "output_keys": ["final_decision"],
                "depends_on": ["step_2"],
                "rationale": "Return a signal-only BUY/SELL/HOLD decision.",
            },
        ]
        return {
            "stage": "constrained_search_stage",
            "method": "DataEvolver",
            "mode": "signal_only_profit_guard",
            "final_pipeline": nodes,
            "nodes": nodes,
            "edges": [
                {"from": dep, "to": node["step_id"], "message": "structured signal output"}
                for node in nodes
                for dep in node.get("depends_on", [])
            ],
            "execution_order": [node["step_id"] for node in nodes],
            "llm_constrained_search": {},
        }

    def _signal_only_execution(
        self,
        state: AgentState,
        data_profile: dict[str, Any],
        technical: dict[str, Any],
        decision: dict[str, Any],
        execution_order: list[str],
    ) -> dict[str, Any]:
        market_context = {
            "ticker": state.get("ticker", ""),
            "trade_date": state.get("trade_date", ""),
            "technical": technical,
            "fundamental_stance": ((state.get("local_evidence") or {}).get("fundamental") or {}).get("stance", "unknown"),
            "news_stance": ((state.get("local_evidence") or {}).get("news") or {}).get("stance", "unknown"),
            "policy_stance": ((state.get("local_evidence") or {}).get("policy") or {}).get("stance", "unknown"),
        }
        risk_gate = {
            "sell_first": bool(technical.get("sell_signal")),
            "entry_allowed": bool(technical.get("buy_signal")) and not bool(technical.get("sell_signal")),
            "hold_required": not bool(technical.get("buy_signal")) and not bool(technical.get("sell_signal")),
            "selected_signal": decision.get("action", "HOLD"),
            "rule": "SELL if sell_signal; BUY if buy_signal; otherwise HOLD.",
        }
        node_outputs = {
            "step_1": {
                "operator": "read_market_data",
                "output": {"market_context": market_context},
                "quality_evaluation": {
                    "passed": True,
                    "score": 1.0,
                    "feedback": "Current evidence was converted into structured signal context.",
                },
                "attempts": 1,
            },
            "step_2": {
                "operator": "risk_management",
                "output": {"risk_gate": risk_gate},
                "quality_evaluation": {
                    "passed": True,
                    "score": 1.0,
                    "feedback": "Risk gate gives exit signals priority and blocks entries without buy_signal.",
                },
                "attempts": 1,
            },
            "step_3": {
                "operator": "join",
                "output": {"final_decision": decision},
                "quality_evaluation": self._evaluate_signal_decision(technical, decision),
                "attempts": 1,
            },
        }
        return {
            "stage": "dag_execution",
            "mode": "signal_only_agents_with_quality_checks",
            "execution_order": execution_order,
            "node_outputs": node_outputs,
            "data_store_keys": [
                "raw_evidence",
                "data_profile",
                "market_context",
                "risk_gate",
                "final_decision",
                "final_decision_structured",
            ],
            "final_decision_structured": decision,
        }

    def _decision_from_technical_signal(self, state: AgentState, technical: dict[str, Any]) -> dict[str, Any]:
        sell_signal = bool(technical.get("sell_signal"))
        buy_signal = bool(technical.get("buy_signal"))
        if sell_signal:
            action = "SELL"
            position_pct = -100.0
            posture = "signal_only_exit"
            primary_reason = str(technical.get("exit_reason") or "Technical sell_signal is active.")
        elif buy_signal:
            action = "BUY"
            position_pct = 100.0
            posture = "signal_only_entry"
            primary_reason = str(technical.get("entry_reason") or "Technical buy_signal is active.")
        else:
            action = "HOLD"
            position_pct = 0.0
            posture = "signal_only_wait"
            primary_reason = "No validated technical entry or exit signal is active."

        instruction = {
            "action": action,
            "position_pct": position_pct,
            "allocation_posture": posture,
            "reasoning": (
                f"{primary_reason} DataEvolver emits only the trading signal; position sizing is reserved "
                "for compatibility with replay scripts."
            ),
            "supporting_evidence": [
                f"mode={technical.get('mode', 'unknown')}",
                f"buy_signal={buy_signal}",
                f"sell_signal={sell_signal}",
                f"close={_fmt_float(technical.get('adjusted_close'))}",
                f"ma10={_fmt_float(technical.get('ma10'))}",
                f"ma20={_fmt_float(technical.get('ma20'))}",
                f"from_20d_low={_fmt_float(technical.get('from_low20_pct'))}%",
                f"drawdown60={_fmt_float(technical.get('drawdown60_pct'))}%",
            ],
            "opposing_evidence": self._opposing_signal_evidence(technical),
            "key_risks": [
                "Signal-only replay can be sensitive to same-day execution assumptions.",
                "Local technical evidence does not forecast overnight gaps or new unseen news.",
            ],
        }
        decision = decision_from_instruction(instruction, self.max_position_pct, "dataevolver_signal_agent")
        decision["signal"] = action
        decision["trading_signal"] = action
        decision["signal_only"] = True
        decision["suppress_position_output"] = True
        decision["llm_decision_mode"] = "signal_only_profit_guard"
        decision["technical_signal"] = {
            "buy_signal": buy_signal,
            "sell_signal": sell_signal,
            "mode": technical.get("mode", "unknown"),
        }
        return decision

    def _technical_signal(self, state: AgentState) -> dict[str, Any]:
        evidence = state.get("local_evidence") or {}
        technical = evidence.get("technical") or {}
        return technical if isinstance(technical, dict) else {}

    def _opposing_signal_evidence(self, technical: dict[str, Any]) -> list[str]:
        opposing = []
        if technical.get("buy_signal") and technical.get("sell_signal"):
            opposing.append("Both buy_signal and sell_signal are active; sell_signal takes precedence.")
        if not technical.get("buy_signal") and not technical.get("sell_signal"):
            opposing.append("No entry or exit trigger is active, so the signal remains HOLD.")
        if technical.get("drawdown60_pct", 0.0) <= -15.0:
            opposing.append("Deep 60-day drawdown increases whipsaw risk.")
        return opposing

    def _evaluate_signal_decision(self, technical: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        expected = "SELL" if technical.get("sell_signal") else "BUY" if technical.get("buy_signal") else "HOLD"
        action = str(decision.get("action") or "HOLD").upper()
        passed = action == expected
        return {
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "feedback": (
                "Final signal matches the technical guard."
                if passed
                else f"Expected {expected} from technical guard but received {action}."
            ),
            "expected_signal": expected,
            "actual_signal": action,
        }

    def _result_update(
        self,
        state: AgentState,
        data_profile: dict[str, Any],
        understanding_result: dict[str, Any],
        blueprint: dict[str, Any],
        template_plan: dict[str, Any],
        logical_plan: dict[str, Any],
        validation: dict[str, Any],
        execution: dict[str, Any],
        status: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_plan = {
            "method": "DataEvolver",
            "mode": "understanding_freefit_template_constrained_search",
            "ticker": state.get("ticker", ""),
            "trade_date": state.get("trade_date", ""),
            "operator_manual": operator_manual(),
            "available_templates": TRADING_TEMPLATES,
            "data_profile": data_profile,
            "understanding_result": understanding_result,
            "free_fitting_stage": blueprint,
            "template_combination_stage": template_plan,
            "constrained_search_stage": logical_plan,
            "logical_checker": validation,
        }
        signal_only = bool(decision.get("signal_only"))
        workflow_outputs = {
            "dag_execution": execution,
            "final_decision_structured": decision,
            "decision_contract": {
                "allowed_actions": ["BUY", "SELL", "HOLD"],
                "primary_output": "trading_signal" if signal_only else "action_with_position_pct",
                "position_pct_unit": "compatibility_only_percent" if signal_only else "percent",
                "max_buy_position_pct": self.max_position_pct,
                "suppress_position_output": signal_only,
            },
        }
        return {
            "workflow_mode": "dataevolver",
            "workflow_method": "DataEvolver",
            "workflow_status": status,
            "workflow_plan": workflow_plan,
            "workflow_outputs": workflow_outputs,
            "team_plan": workflow_plan,
            "module_outputs": {"dataevolver": workflow_outputs},
            "generated_skills": operator_manual(),
            "expert_agents": [
                {"name": node.get("step_id"), "operator": node.get("operator"), "depends_on": node.get("depends_on", [])}
                for node in logical_plan.get("nodes", [])
            ] if logical_plan else [],
            "expert_outputs": execution.get("node_outputs", {}) if execution else {},
            "team_discussion_summary": (
                "DataEvolver built a signal-only DAG, evaluated each node output, "
                "and emitted the final BUY/SELL/HOLD trading signal."
                if signal_only
                else (
                    "DataEvolver built a DAG, executed every operator as an evaluated LLM agent, "
                    "and used the join agent for the final decision."
                )
            ),
            "team_summary": {
                "workflow": "dataevolver",
                "status": status,
                "signal": decision.get("action", "HOLD"),
            },
            "final_decision_structured": decision,
            "final_decision": _format_signal_only_decision(decision) if signal_only else format_final_decision(decision),
        }


def run_dataevolver_workflow(state: AgentState, llm: Any | None = None) -> dict[str, Any]:
    max_position_pct = state.get("max_position_pct", 100.0)
    return DataEvolverWorkflow(max_position_pct=max_position_pct, llm=llm).run(state)


def create_dataevolver_node(llm: Any | None = None):
    def _node(state: AgentState) -> dict[str, Any]:
        return run_dataevolver_workflow(state, llm=llm)

    return _node


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
    node_ids = [str(node.get("step_id") or node.get("id") or "") for node in nodes]
    deps = {
        str(node.get("step_id") or node.get("id") or ""): set(_as_list(node.get("depends_on")))
        for node in nodes
    }
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


def _json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return clip_text(text, limit)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _format_signal_only_decision(decision: dict[str, Any]) -> str:
    lines = [
        f"Trading Signal: {decision.get('trading_signal', decision.get('action', 'HOLD'))}",
        "",
        f"Reasoning: {decision.get('reasoning', '')}",
    ]
    if decision.get("supporting_evidence"):
        lines.append("Supporting Evidence: " + "; ".join(_as_list(decision.get("supporting_evidence"))))
    if decision.get("opposing_evidence"):
        lines.append("Opposing Evidence: " + "; ".join(_as_list(decision.get("opposing_evidence"))))
    if decision.get("key_risks"):
        lines.append("Key Risks: " + "; ".join(_as_list(decision.get("key_risks"))))
    return "\n".join(lines)


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"
