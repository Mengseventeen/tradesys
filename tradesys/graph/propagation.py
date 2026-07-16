from typing import Any, Dict

from langchain_core.messages import HumanMessage


class Propagator:
    """Create initial state and graph invocation config."""

    def __init__(
        self,
        recursion_limit: int = 80,
        max_position_pct: float = 10.0,
        execution_mode: str = "baseline",
    ):
        self.recursion_limit = recursion_limit
        self.max_position_pct = min(100.0, max(0.0, float(max_position_pct or 0.0)))
        self.execution_mode = execution_mode

    def create_initial_state(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        return {
            "messages": [HumanMessage(content="Start parallel analyst workflow.")],
            "technical_messages": [],
            "fundamental_messages": [],
            "news_messages": [],
            "policy_messages": [],
            "ticker": ticker,
            "trade_date": trade_date,
            "max_position_pct": self.max_position_pct,
            "execution_mode": self.execution_mode,
            "technical_report": "",
            "fundamental_report": "",
            "news_report": "",
            "policy_report": "",
            "analyst_reports": [],
            "errors": [],
            "error": None,
            "workflow_mode": "",
            "team_plan": {},
            "generated_skills": [],
            "expert_agents": [],
            "expert_outputs": [],
            "module_outputs": {},
            "team_discussion_summary": "",
            "team_summary": {},
            "final_decision_structured": {},
            "final_decision": "",
            "local_evidence": {},
            "workflow_method": "",
            "workflow_plan": {},
            "workflow_outputs": {},
            "workflow_status": "not_started",
        }

    def get_graph_config(self) -> Dict[str, Any]:
        return {
            "recursion_limit": self.recursion_limit,
        }
