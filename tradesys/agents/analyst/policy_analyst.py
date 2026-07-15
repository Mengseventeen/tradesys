from langchain_core.messages import RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import ToolNode

from tradesys.agents.utils.agent_states import AgentState
from tradesys.agents.utils.policy_data_tools import (
    get_economic_data,
    get_federal_funds_rate,
    get_latest_economic_summary,
    get_macro_summary,
    get_treasury_yield,
)
from tradesys.agents.utils.report_logger import get_report_logger


POLICY_TOOLS = [
    get_economic_data,
    get_macro_summary,
    get_federal_funds_rate,
    get_treasury_yield,
    get_latest_economic_summary,
]


POLICY_SYSTEM_MESSAGE = """
You are a macro policy analyst tasked with analyzing the policy and
macroeconomic backdrop for the given ticker as of the trade date. Treat the
trade date as the analysis cutoff and do not use future information. Use the
available tools to inspect macroeconomic and policy-sensitive data; let the
tools provide the numbers and do not invent data.

Write a comprehensive, trader-facing report on how the macro and policy
environment may affect the ticker. Include interest-rate context, Treasury
yield conditions, inflation, growth, labor-market or consumer data when
available, policy-sensitive risks, and implications for valuation, demand,
financing conditions, risk appetite, and trade timing. Provide specific,
actionable insights with supporting evidence so traders can judge whether the
macro backdrop supports buying, holding, or selling. If the tools do not provide
a data point, state the limitation clearly.

Final report format:
1. Macro backdrop
2. Policy and rate environment
3. Transmission to the company or sector
4. Key macro risks and uncertainties
5. Final view: bullish, bearish, or neutral

Append a Markdown table at the end that organizes the key macro/policy points,
supporting evidence, trading implication, and confidence/risk note.
"""


def _active_messages(messages):
    return [msg for msg in messages if not isinstance(msg, RemoveMessage)]


def create_policy_analyst(llm):
    def policy_analyst(state: AgentState) -> dict:
        ticker = state["ticker"]
        trade_date = state["trade_date"]
        messages = _active_messages(state.get("policy_messages", []))

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_message}\nAvailable tools: {tool_names}"),
            ("user", "Ticker: {ticker}\nTrade date: {trade_date}"),
            MessagesPlaceholder(variable_name="messages"),
        ])

        chain = prompt | llm.bind_tools(POLICY_TOOLS)
        result = chain.invoke({
            "system_message": POLICY_SYSTEM_MESSAGE,
            "tool_names": ", ".join(tool.name for tool in POLICY_TOOLS),
            "ticker": ticker,
            "trade_date": trade_date,
            "messages": messages,
        })

        update = {"policy_messages": [result]}

        if not getattr(result, "tool_calls", None):
            report = result.content
            update["policy_report"] = report
            get_report_logger().log_policy_report(report, ticker, trade_date)

        return update

    return policy_analyst


def create_policy_tools_node():
    return ToolNode(POLICY_TOOLS, messages_key="policy_messages")
