from __future__ import annotations

import unittest
from types import SimpleNamespace

from tradesys.workflows.ptc_runtime import (
    PTCProgramCompiler,
    PTCProgramRuntime,
    select_market_strategy,
    validate_ptc_program,
)
from tradesys.workflows.trading_operators import TRADING_OPERATOR_REGISTRY, operator_specs_by_name


DEPENDENCIES = {
    "read_market_data": [],
    "bullish_signal": ["step_1"],
    "bearish_signal": ["step_1"],
    "disagreement_detection": ["step_1", "step_2", "step_3"],
    "risk_management": ["step_1", "step_3", "step_4"],
    "position_sizing": ["step_2", "step_3", "step_4", "step_5"],
    "join": ["step_6"],
}


def sample_plan() -> dict:
    return {
        "nodes": [
            {
                "step_id": f"step_{index}",
                "operator": spec.name,
                "depends_on": DEPENDENCIES[spec.name],
            }
            for index, spec in enumerate(TRADING_OPERATOR_REGISTRY, start=1)
        ]
    }


class FakeAgentExecutor:
    def run_agent(self, operator: str, _data: dict):
        outputs = {
            "read_market_data": {"market_context": {"ticker": "AMZN"}},
            "bullish_signal": {"bullish_view": {"report": "bullish"}},
            "bearish_signal": {"bearish_view": {"report": "bearish"}},
            "disagreement_detection": {"disagreement_report": {"report": "mixed"}},
            "risk_management": {"risk_profile": {"risk_level": "medium"}},
            "position_sizing": {"trade_instruction": {"action": "HOLD", "position_pct": 0}},
            "join": {"final_decision": {"action": "HOLD", "position_pct": 0}},
        }
        return SimpleNamespace(
            operator_output=outputs[operator],
            evaluation={"passed": True, "score": 1.0},
            attempts=[],
        )


class PTCProgramTests(unittest.TestCase):
    def test_static_program_parallelizes_directional_branches(self):
        program = PTCProgramCompiler().compile_static(sample_plan())
        result = PTCProgramRuntime(FakeAgentExecutor()).execute(
            program,
            {"raw_evidence": {}, "data_profile": {}},
        )
        self.assertEqual(result["execution_layers"][1], ["step_2", "step_3"])
        self.assertEqual(result["final_decision_structured"]["action"], "HOLD")

    def test_dynamic_risk_off_skips_bullish_and_disagreement_agents(self):
        profile = {
            "technical": {
                "buy_signal": False,
                "sell_signal": True,
                "volatility_pct": 5.0,
                "drawdown60_pct": -20.0,
            },
            "fundamental": {"stance": "neutral"},
            "news": {"stance": "neutral"},
            "policy": {"restrictive_policy": True},
        }
        program = PTCProgramCompiler().compile_dynamic(sample_plan(), profile)
        result = PTCProgramRuntime(FakeAgentExecutor()).execute(
            program,
            {"raw_evidence": {}, "data_profile": profile},
        )
        constants = [item for item in result["call_trace"] if item["kind"] == "constant"]
        self.assertEqual(program["strategy"], "risk_off_bearish_focus")
        self.assertEqual({item["operator"] for item in constants}, {"bullish_signal", "disagreement_detection"})

    def test_clean_bullish_route_skips_bearish_agent(self):
        profile = {
            "technical": {
                "buy_signal": True,
                "sell_signal": False,
                "volatility_pct": 1.0,
                "drawdown60_pct": -2.0,
            },
            "fundamental": {"stance": "bullish"},
            "news": {"stance": "bullish"},
            "policy": {"restrictive_policy": False},
        }
        strategy = select_market_strategy(profile)
        self.assertEqual(strategy["name"], "clean_bullish_focus")
        self.assertFalse(strategy["run_bearish_agent"])

    def test_validator_rejects_unknown_instruction_kind(self):
        program = PTCProgramCompiler().compile_static(sample_plan())
        program["instructions"][0]["kind"] = "python_exec"
        validation = validate_ptc_program(program, operator_specs_by_name())
        self.assertFalse(validation["is_valid"])
        self.assertTrue(any("forbidden" in issue for issue in validation["issues"]))


if __name__ == "__main__":
    unittest.main()
