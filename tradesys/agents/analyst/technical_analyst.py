from langchain_core.messages import RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import ToolNode

from tradesys.agents.utils.agent_states import AgentState
from tradesys.agents.utils.report_logger import get_report_logger
from tradesys.agents.utils.technical_indicators_tools import (
    list_available_stocks,
    list_available_indicators,
    get_indicator_data,
    get_indicators_data,
    get_indicator_on_date,
    get_stock_data,
)


TECHNICAL_TOOLS = [
    list_available_stocks,
    list_available_indicators,
    get_stock_data,
    get_indicator_data,
    get_indicators_data,
    get_indicator_on_date,
]


TECHNICAL_SYSTEM_MESSAGE = """
You are a technical analyst tasked with analyzing price action and technical
indicators for the given ticker as of the trade date. Treat the trade date as
the analysis cutoff and do not use future information. Use the available tools
to inspect recent OHLCV data and relevant indicators; let the tools provide
the data and do not invent numbers.

Write a comprehensive, trader-facing report with as much useful detail as the
tool evidence supports. Include specific price levels, trend direction, moving
average or support/resistance context, momentum readings, volume behavior when
available, bullish and bearish technical evidence, and actionable implications
for entry, hold, or exit decisions. If a useful data point is unavailable, say
so plainly instead of filling the gap.

Final report format:
1. Key observations
2. Technical interpretation
3. Trading implications and risk controls
4. Final view: bullish, bearish, or neutral

Append a Markdown table at the end that organizes the key technical evidence,
signal direction, trading implication, and confidence/risk note.
"""


def _active_messages(messages):
    return [msg for msg in messages if not isinstance(msg, RemoveMessage)]


def create_technical_analyst(llm):
    def technical_analyst(state: AgentState) -> dict:
        ticker = state["ticker"]
        trade_date = state["trade_date"]
        messages = _active_messages(state.get("technical_messages", []))

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_message}\nAvailable tools: {tool_names}"),
            ("user", "Ticker: {ticker}\nTrade date: {trade_date}"),
            MessagesPlaceholder(variable_name="messages"),
        ])

        chain = prompt | llm.bind_tools(TECHNICAL_TOOLS)
        result = chain.invoke({
            "system_message": TECHNICAL_SYSTEM_MESSAGE,
            "tool_names": ", ".join(tool.name for tool in TECHNICAL_TOOLS),
            "ticker": ticker,
            "trade_date": trade_date,
            "messages": messages,
        })

        update = {"technical_messages": [result]}

        if not getattr(result, "tool_calls", None):
            report = result.content
            update["technical_report"] = report
            get_report_logger().log_technical_report(report, ticker, trade_date)

        return update

    return technical_analyst


def create_technical_tools_node():
    return ToolNode(TECHNICAL_TOOLS, messages_key="technical_messages")
