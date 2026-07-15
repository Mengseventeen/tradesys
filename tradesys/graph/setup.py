from langgraph.graph import END, START, StateGraph

from tradesys.agents.analyst.fundamental_analyst import (
    create_fundamental_analyst,
    create_fundamental_tools_node,
)
from tradesys.agents.analyst.news_analyst import (
    create_news_analyst,
    create_news_tools_node,
)
from tradesys.agents.analyst.policy_analyst import (
    create_policy_analyst,
    create_policy_tools_node,
)
from tradesys.agents.analyst.technical_analyst import (
    create_technical_analyst,
    create_technical_tools_node,
)
from tradesys.agents.utils.agent_states import AgentState
from tradesys.graph.conditional_logic import ConditionalLogic
from tradesys.workflows import create_dataevolver_node, create_llmcompiler_node


class GraphSetup:
    """Build a four-analyst workflow with a selectable decision compiler."""

    def __init__(self, llm, decision_workflow: str = "llmcompiler"):
        self.llm = llm
        self.decision_workflow = decision_workflow
        self.conditional_logic = ConditionalLogic()

    def setup_graph(self):
        workflow = StateGraph(AgentState)

        self._add_nodes(workflow)
        self._add_edges(workflow)

        return workflow.compile()

    def _add_nodes(self, workflow: StateGraph):
        workflow.add_node("technical_analyst", create_technical_analyst(self.llm))
        workflow.add_node("technical_tools", create_technical_tools_node())

        workflow.add_node("fundamental_analyst", create_fundamental_analyst(self.llm))
        workflow.add_node("fundamental_tools", create_fundamental_tools_node())

        workflow.add_node("news_analyst", create_news_analyst(self.llm))
        workflow.add_node("news_tools", create_news_tools_node())

        workflow.add_node("policy_analyst", create_policy_analyst(self.llm))
        workflow.add_node("policy_tools", create_policy_tools_node())

        workflow.add_node("technical_done", _done_node)
        workflow.add_node("fundamental_done", _done_node)
        workflow.add_node("news_done", _done_node)
        workflow.add_node("policy_done", _done_node)

        workflow.add_node("decision_workflow", self._create_decision_node())

    def _add_edges(self, workflow: StateGraph):
        workflow.add_edge(START, "technical_analyst")
        workflow.add_edge(START, "fundamental_analyst")
        workflow.add_edge(START, "news_analyst")
        workflow.add_edge(START, "policy_analyst")

        workflow.add_conditional_edges(
            "technical_analyst",
            self._route_technical,
            {"tools": "technical_tools", "end": "technical_done"},
        )
        workflow.add_edge("technical_tools", "technical_analyst")

        workflow.add_conditional_edges(
            "fundamental_analyst",
            self._route_fundamental,
            {"tools": "fundamental_tools", "end": "fundamental_done"},
        )
        workflow.add_edge("fundamental_tools", "fundamental_analyst")

        workflow.add_conditional_edges(
            "news_analyst",
            self._route_news,
            {"tools": "news_tools", "end": "news_done"},
        )
        workflow.add_edge("news_tools", "news_analyst")

        workflow.add_conditional_edges(
            "policy_analyst",
            self._route_policy,
            {"tools": "policy_tools", "end": "policy_done"},
        )
        workflow.add_edge("policy_tools", "policy_analyst")

        workflow.add_edge(
            ["technical_done", "fundamental_done", "news_done", "policy_done"],
            "decision_workflow",
        )
        workflow.add_edge("decision_workflow", END)

    def _create_decision_node(self):
        if self.decision_workflow == "dataevolver":
            return create_dataevolver_node(self.llm)
        return create_llmcompiler_node(self.llm)

    def _route_technical(self, state: AgentState) -> str:
        return self.conditional_logic.should_continue_analysis(state, "technical_messages")

    def _route_fundamental(self, state: AgentState) -> str:
        return self.conditional_logic.should_continue_analysis(state, "fundamental_messages")

    def _route_news(self, state: AgentState) -> str:
        return self.conditional_logic.should_continue_analysis(state, "news_messages")

    def _route_policy(self, state: AgentState) -> str:
        return self.conditional_logic.should_continue_analysis(state, "policy_messages")


def create_workflow(llm, decision_workflow: str = "llmcompiler"):
    return GraphSetup(llm, decision_workflow=decision_workflow).setup_graph()


def _done_node(_state: AgentState) -> dict:
    return {}
