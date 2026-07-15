from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tradesys.workflows.common import clip_text, decision_from_instruction
from tradesys.workflows.llm_client import invoke_json, require_llm
from tradesys.workflows.trading_operators import TradingOperatorSpec, operator_specs_by_name


@dataclass
class AgentRunResult:
    operator_output: dict[str, Any]
    evaluation: dict[str, Any]
    attempts: list[dict[str, Any]]


class LLMTradingAgentExecutor:
    """Execute each trading DAG operator as an LLM agent with evaluate-and-revise."""

    def __init__(
        self,
        llm: Any | None,
        max_position_pct: float,
        source: str,
        *,
        max_attempts: int = 3,
        min_quality_score: float = 0.72,
    ) -> None:
        self.llm = require_llm(llm, f"{source} LLM trading agents")
        self.max_position_pct = min(100.0, max(0.0, float(max_position_pct or 100.0)))
        self.source = source
        self.max_attempts = max(1, int(max_attempts))
        self.min_quality_score = min(1.0, max(0.0, float(min_quality_score)))
        self.operator_specs = operator_specs_by_name()

    def run_operator(self, operator: str, data_store: dict[str, Any]) -> dict[str, Any]:
        return self.run_agent(operator, data_store).operator_output

    def run_agent(self, operator: str, data_store: dict[str, Any]) -> AgentRunResult:
        spec = self.operator_specs.get(operator)
        if spec is None:
            raise ValueError(f"Unsupported LLM trading operator: {operator}")

        feedback = ""
        attempts: list[dict[str, Any]] = []
        best_output: dict[str, Any] | None = None
        best_evaluation: dict[str, Any] | None = None
        best_score = -1.0

        for attempt_no in range(1, self.max_attempts + 1):
            raw_output = self._invoke_agent(spec, data_store, feedback, attempt_no)
            normalized_output, structural_issues = self._normalize_output(spec, raw_output)
            evaluation = self._evaluate_output(spec, data_store, normalized_output, structural_issues)
            score = _float(evaluation.get("score"), 0.0)

            attempts.append({
                "attempt": attempt_no,
                "output": normalized_output,
                "evaluation": evaluation,
            })
            if score > best_score:
                best_score = score
                best_output = normalized_output
                best_evaluation = evaluation

            if self._is_acceptable(evaluation, structural_issues):
                return AgentRunResult(normalized_output, evaluation, attempts)

            feedback = self._revision_feedback(evaluation, structural_issues, normalized_output)

        if best_output is None or best_evaluation is None:
            raise ValueError(f"{spec.name} LLM agent did not produce any output.")
        best_evaluation = dict(best_evaluation)
        best_evaluation["accepted_after_max_attempts"] = False
        return AgentRunResult(best_output, best_evaluation, attempts)

    def _invoke_agent(
        self,
        spec: TradingOperatorSpec,
        data_store: dict[str, Any],
        feedback: str,
        attempt_no: int,
    ) -> dict[str, Any]:
        output_key = spec.output_keys[0]
        system = (
            "You are an autonomous trading DAG agent executing exactly one node. "
            "Generate new analysis from the supplied inputs; do not concatenate upstream reports or copy templates. "
            "Use only supplied evidence, keep claims grounded, and return exactly one valid JSON object. "
            "Directional branch agents are allowed to conclude that their side is weak or not actionable; "
            "do not force a bullish or bearish thesis when the evidence does not support it. "
            f"The JSON object must contain the top-level key '{output_key}' and no markdown fences."
        )
        user = (
            f"Operator: {spec.name}\n"
            f"Category: {spec.category}\n"
            f"Task: {spec.description}\n"
            f"Expected input keys: {list(spec.input_keys)}\n"
            f"Expected output key: {output_key}\n"
            f"Max BUY position pct: {self.max_position_pct}\n\n"
            f"Inputs available to this node:\n{_json(self._input_context(spec, data_store), 18000)}\n\n"
            f"Output guidance:\n{_json(_output_guidance(spec.name, output_key), 7000)}\n"
        )
        if feedback:
            user += (
                "\nThe previous attempt did not pass evaluation. Revise it using this feedback:\n"
                f"{clip_text(feedback, 5000)}\n"
            )
        user += f"\nAttempt {attempt_no}: return the JSON now."
        return invoke_json(self.llm, system, user)

    def _input_context(self, spec: TradingOperatorSpec, data_store: dict[str, Any]) -> dict[str, Any]:
        context = {
            key: data_store.get(key)
            for key in spec.input_keys
        }
        context["max_buy_position_pct"] = self.max_position_pct
        if "data_profile" in data_store and "data_profile" not in context:
            context["data_profile"] = data_store.get("data_profile")
        return context

    def _normalize_output(
        self,
        spec: TradingOperatorSpec,
        raw_output: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        output_key = spec.output_keys[0]
        issues: list[str] = []
        raw = raw_output if isinstance(raw_output, dict) else {}
        value = raw.get(output_key)

        if value is None and spec.name in {"position_sizing", "join"} and "action" in raw:
            value = raw
        if value is None:
            issues.append(f"missing expected output key: {output_key}")
            value = self._invalid_payload(spec, raw)
        if not isinstance(value, dict):
            issues.append(f"{output_key} must be a JSON object")
            value = {"value": value, "report": str(value)}

        if spec.name in {"position_sizing", "join"}:
            action = str(value.get("action", "")).upper()
            if action not in {"BUY", "SELL", "HOLD"}:
                issues.append(f"{output_key} has invalid or missing action")
            elif not value.get("allocation_posture"):
                value = dict(value)
                value["allocation_posture"] = f"{spec.name}_{action.lower()}"
            agent_report = str(value.get("report") or "").strip()
            if agent_report and not value.get("reasoning"):
                value = dict(value)
                value["reasoning"] = agent_report
            source = f"{self.source}_{spec.name}_agent"
            normalized_value = decision_from_instruction(value, self.max_position_pct, source)
            if agent_report:
                normalized_value["report"] = agent_report
            value = normalized_value

        return {output_key: value}, issues

    def _invalid_payload(self, spec: TradingOperatorSpec, raw_output: dict[str, Any]) -> dict[str, Any]:
        if spec.name == "join":
            return {
                "action": "HOLD",
                "position_pct": 0.0,
                "allocation_posture": f"{self.source}_invalid_join_output",
                "reasoning": "The join agent did not return a usable final_decision object.",
                "key_risks": ["Invalid join agent output."],
            }
        return {
            "report": "The LLM agent did not return the expected structured output.",
            "agent_error": f"missing expected output key for {spec.name}",
            "raw_response_excerpt": clip_text(json.dumps(raw_output, ensure_ascii=False, default=str), 1200),
        }

    def _evaluate_output(
        self,
        spec: TradingOperatorSpec,
        data_store: dict[str, Any],
        output: dict[str, Any],
        structural_issues: list[str],
    ) -> dict[str, Any]:
        heuristic = self._heuristic_evaluation(spec, output, structural_issues)
        system = (
            "You are a strict evaluator for one trading DAG agent output. "
            "Score whether the node output is grounded in its inputs, does fresh reasoning, satisfies schema, "
            "and avoids simple concatenation of upstream report text. "
            "Evaluate according to the operator's intent: bullish_signal and bearish_signal are branch-view agents, "
            "so do not fail them merely because the total market context leans the other way. They pass when they "
            "ground the branch view, acknowledge contrary evidence, use low confidence/HOLD for weak branch evidence, "
            "and avoid overstating the case. Fail them when action_bias or confidence is unsupported, when contrary "
            "evidence is ignored, or when the output is just copied from inputs. For join, fail missing reasoning, "
            "evidence, risks, or an allocation posture that does not match the decision. Return JSON only."
        )
        user = (
            f"Operator spec:\n{_json(spec.to_dict(), 4000)}\n\n"
            f"Node inputs:\n{_json(self._input_context(spec, data_store), 12000)}\n\n"
            f"Candidate output:\n{_json(output, 12000)}\n\n"
            f"Known structural issues:\n{_json(structural_issues, 2000)}\n\n"
            "Return JSON with this schema:\n"
            "{\n"
            '  "score": 0.0,\n'
            '  "passed": false,\n'
            '  "issues": ["specific issue"],\n'
            '  "revision_brief": "how the agent should improve the next attempt"\n'
            "}"
        )
        try:
            parsed = invoke_json(self.llm, system, user)
        except Exception as exc:
            heuristic["evaluator_error"] = str(exc)
            return heuristic

        if not parsed:
            return heuristic
        score = min(1.0, max(0.0, _float(parsed.get("score"), heuristic["score"])))
        issues = _as_list(parsed.get("issues")) + list(structural_issues)
        critical_issues = [issue for issue in issues if _is_critical_issue(issue)]
        branch_calibrated = _branch_calibration_passes(spec.name, output.get(spec.output_keys[0]))
        passed = (
            not structural_issues
            and not critical_issues
            and (
                (bool(parsed.get("passed")) and score >= self.min_quality_score)
                or branch_calibrated
                or (heuristic.get("passed") and score >= 0.85)
            )
        )
        return {
            "score": max(score, self.min_quality_score) if passed else score,
            "passed": passed,
            "issues": [] if passed else _dedupe(issues),
            "warnings": _dedupe(issues) if passed and issues else [],
            "revision_brief": str(parsed.get("revision_brief") or heuristic.get("revision_brief") or ""),
            "evaluator": "llm_with_rule_calibration" if passed else "llm",
        }

    def _heuristic_evaluation(
        self,
        spec: TradingOperatorSpec,
        output: dict[str, Any],
        structural_issues: list[str],
    ) -> dict[str, Any]:
        output_key = spec.output_keys[0]
        value = output.get(output_key)
        issues = list(structural_issues)
        score = 1.0
        if structural_issues:
            score -= 0.35
        if not isinstance(value, dict):
            issues.append(f"{output_key} is not an object")
            score -= 0.25
        else:
            narrative = " ".join(
                str(value.get(key, ""))
                for key in ("report", "reasoning", "summary", "thesis", "risk_thesis", "sizing_guidance")
            ).strip()
            if len(narrative) < 80 and spec.name not in {"join"}:
                issues.append("output does not contain enough generated reasoning")
                score -= 0.2
            if _looks_like_template(narrative):
                issues.append("output looks like a template or concatenated report")
                score -= 0.25
            if spec.name == "join" and str(value.get("action", "")).upper() not in {"BUY", "SELL", "HOLD"}:
                issues.append("join output has invalid action")
                score -= 0.3

        score = min(1.0, max(0.0, score))
        return {
            "score": score,
            "passed": not issues and score >= self.min_quality_score,
            "issues": _dedupe(issues),
            "revision_brief": "Address schema, grounding, and reasoning issues before returning the same output.",
            "evaluator": "heuristic",
        }

    def _is_acceptable(self, evaluation: dict[str, Any], structural_issues: list[str]) -> bool:
        return (
            not structural_issues
            and bool(evaluation.get("passed"))
            and not _as_list(evaluation.get("issues"))
            and _float(evaluation.get("score"), 0.0) >= self.min_quality_score
        )

    def _revision_feedback(
        self,
        evaluation: dict[str, Any],
        structural_issues: list[str],
        output: dict[str, Any],
    ) -> str:
        issues = _dedupe(_as_list(evaluation.get("issues")) + list(structural_issues))
        return (
            f"Quality score: {evaluation.get('score', 0.0)}\n"
            f"Issues: {json.dumps(issues, ensure_ascii=False)}\n"
            f"Revision brief: {evaluation.get('revision_brief', '')}\n"
            "If the branch evidence is weak, say so directly and use HOLD/low confidence instead of forcing a thesis.\n"
            f"Previous output excerpt:\n{_json(output, 6000)}"
        )


def _output_guidance(operator: str, output_key: str) -> dict[str, Any]:
    guidance: dict[str, Any] = {
        "top_level_shape": {output_key: "object"},
        "common_rules": [
            "write a fresh analytical report, not a concatenation of upstream reports",
            "cite concrete evidence fields from the input when making claims",
            "separate supporting evidence, opposing evidence, and risks when relevant",
        ],
    }
    if operator == "read_market_data":
        guidance[output_key] = {
            "report": "integrated market context in prose",
            "technical": "salient technical evidence",
            "fundamental": "salient fundamental evidence",
            "news": "salient news evidence",
            "policy": "salient policy evidence",
            "data_quality_notes": ["missing or stale inputs"],
        }
    elif operator == "bullish_signal":
        guidance[output_key] = {
            "report": "buy-side evidence assessment; explicitly state when there is no actionable bullish case",
            "thesis": "concise bullish thesis, or 'no actionable bullish thesis'",
            "supporting_evidence": ["input-grounded evidence"],
            "cautions": ["limits to the bullish case"],
            "confidence": 0.0,
            "action_bias": "BUY or HOLD; use HOLD when bullish evidence is weak or outweighed",
            "calibration_rules": [
                "If technical sell_signal is active, default to HOLD unless there is concrete contrary evidence.",
                "If bullish evidence is mostly hypothetical or only oversold, use low confidence and emphasize cautions.",
                "Never present a strong bullish thesis without addressing bearish technical, fundamental, policy, or news evidence.",
            ],
        }
    elif operator == "bearish_signal":
        guidance[output_key] = {
            "report": "sell/hold risk evidence assessment; explicitly state when there is no actionable bearish case",
            "risk_thesis": "concise bearish thesis, or 'no actionable bearish thesis'",
            "risk_evidence": ["input-grounded risk evidence"],
            "offsets": ["evidence that weakens the bearish case"],
            "confidence": 0.0,
            "action_bias": "SELL or HOLD; use HOLD when bearish evidence is weak or outweighed",
            "calibration_rules": [
                "If technical buy_signal is active and there is no concrete exit catalyst, default to HOLD.",
                "If bearish evidence is generic uncertainty, use low confidence and emphasize offsets.",
                "Never present a strong bearish thesis without addressing bullish technical, fundamental, policy, or news evidence.",
            ],
        }
    elif operator == "disagreement_detection":
        guidance[output_key] = {
            "report": "analysis of conflicts between branches",
            "has_material_disagreement": False,
            "conflicts": ["specific bullish-vs-bearish disagreement"],
            "resolution_guidance": "how downstream risk/sizing should treat the conflict",
        }
    elif operator == "risk_management":
        guidance[output_key] = {
            "report": "risk assessment with practical controls",
            "risk_level": "low, medium, or high",
            "risk_items": ["specific risk"],
            "sizing_guidance": "risk-aware sizing guidance, not a formula",
            "block_buy": False,
        }
    elif operator == "position_sizing":
        guidance[output_key] = {
            "report": "agent reasoning for provisional trade instruction",
            "action": "BUY, SELL, or HOLD",
            "position_pct": "number; BUY must be 0..max BUY pct, HOLD should be 0",
            "allocation_posture": "short label",
            "reasoning": "grounded explanation",
            "supporting_evidence": ["evidence"],
            "opposing_evidence": ["evidence"],
            "key_risks": ["risk"],
        }
    elif operator == "join":
        guidance[output_key] = {
            "action": "BUY, SELL, or HOLD",
            "position_pct": "number; BUY must be 0..max BUY pct, HOLD should be 0",
            "allocation_posture": "short label",
            "reasoning": "final synthesis grounded in all upstream agent outputs",
            "supporting_evidence": ["evidence"],
            "opposing_evidence": ["evidence"],
            "key_risks": ["risk"],
        }
    return guidance


def _json(value: Any, limit: int) -> str:
    return clip_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), limit)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def _looks_like_template(text: str) -> bool:
    lowered = str(text or "").lower()
    template_markers = [
        "bullish branch report.",
        "bearish branch report.",
        "disagreement report.",
        "risk management report.",
        "positioning advisory report.",
        "upstream outputs were copied together without new analysis.",
    ]
    return any(marker in lowered for marker in template_markers)


def _is_critical_issue(issue: str) -> bool:
    lowered = str(issue or "").lower()
    critical_markers = [
        "missing",
        "invalid",
        "schema",
        "direct repetition",
        "copied",
        "copy",
        "does not provide reasoning",
        "without reasoning",
        "does not contain",
        "unsupported by the evidence",
        "action bias is not adequately supported",
        "action_bias is not adequately supported",
    ]
    return any(marker in lowered for marker in critical_markers)


def _branch_calibration_passes(operator: str, value: Any) -> bool:
    if operator not in {"bullish_signal", "bearish_signal"} or not isinstance(value, dict):
        return False
    action_bias = str(value.get("action_bias", "")).upper()
    confidence = _float(value.get("confidence"), 1.0)
    text = " ".join(
        str(value.get(key, ""))
        for key in ("report", "thesis", "risk_thesis", "summary")
    ).lower()
    weak_markers = [
        "no actionable",
        "weak",
        "not enough",
        "insufficient",
        "outweighed",
        "hold",
        "cautious",
    ]
    has_weak_marker = any(marker in text for marker in weak_markers)
    if action_bias == "HOLD" and confidence <= 0.55 and has_weak_marker:
        return True
    return False
