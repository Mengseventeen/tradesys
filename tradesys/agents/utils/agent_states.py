from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage, RemoveMessage


def messages_reducer(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:
    if not right:
        return left

    if not left:
        return right

    merged = left.copy()
    for message in right:
        if isinstance(message, RemoveMessage):
            merged = [item for item in merged if item.id != message.id]
        else:
            merged.append(message)

    return merged


def list_reducer(left: List[Any], right: List[Any]) -> List[Any]:
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], messages_reducer]
    technical_messages: Annotated[List[BaseMessage], messages_reducer]
    fundamental_messages: Annotated[List[BaseMessage], messages_reducer]
    policy_messages: Annotated[List[BaseMessage], messages_reducer]
    news_messages: Annotated[List[BaseMessage], messages_reducer]

    ticker: str
    trade_date: str
    max_position_pct: float

    technical_report: str
    fundamental_report: str
    policy_report: str
    news_report: str

    analyst_reports: Annotated[List[Dict[str, Any]], list_reducer]
    errors: Annotated[List[str], list_reducer]
    error: Optional[str]

    workflow_mode: str
    team_plan: Dict[str, Any]
    generated_skills: List[Dict[str, Any]]
    expert_agents: List[Dict[str, Any]]
    expert_outputs: List[Dict[str, Any]]
    module_outputs: Dict[str, Any]
    team_discussion_summary: str
    team_summary: Dict[str, Any]
    final_decision_structured: Dict[str, Any]
    final_decision: str

    local_evidence: Dict[str, Any]
    workflow_method: str
    workflow_plan: Dict[str, Any]
    workflow_outputs: Dict[str, Any]
    workflow_status: str
