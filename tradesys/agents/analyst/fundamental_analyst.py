from langchain_core.messages import RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import ToolNode

from tradesys.agents.utils.agent_states import AgentState
from tradesys.agents.utils.ptc_data_tools import collect_fundamental_evidence_ptc
from tradesys.agents.utils.report_logger import get_report_logger


FUNDAMENTAL_TOOLS = [
    collect_fundamental_evidence_ptc,
]


FUNDAMENTAL_SYSTEM_MESSAGE = """
You are a researcher tasked with analyzing fundamental information about the
company for the given ticker as of the trade date. Treat the trade date as the
analysis cutoff and do not use future information. Use the available tools to
inspect financial statements, earnings, and SEC filings; let the tools provide
the data and do not invent numbers. On the first turn, call
collect_fundamental_evidence_ptc exactly once. It joins all required sources;
after receiving its result, write the final report without another tool call.

Write a comprehensive, trader-facing report on the company's fundamental
condition. Include the latest available financial documents, earnings context,
income statement, balance sheet, cash flow, financial history or trend evidence,
quality of growth, profitability, liquidity, cash generation, leverage, and
company-specific risks when the available data supports them. Provide specific,
actionable insights with supporting evidence so traders can judge whether the
fundamentals support buying, holding, or selling. If company profile details or
other facts are not available from the tools, state that limitation instead of
inventing them.

Final report format:
1. Fundamental facts
2. Financial trend and quality analysis
3. Business interpretation for traders
4. Key risks and uncertainties
5. Final view: bullish, bearish, or neutral

Append a Markdown table at the end that organizes the key fundamental points,
supporting evidence, trading implication, and confidence/risk note.
"""


def _active_messages(messages):
    return [msg for msg in messages if not isinstance(msg, RemoveMessage)]


def create_fundamental_analyst(llm):
    def fundamental_analyst(state: AgentState) -> dict:
        ticker = state["ticker"]
        trade_date = state["trade_date"]
        messages = _active_messages(state.get("fundamental_messages", []))

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_message}\nAvailable tools: {tool_names}"),
            ("user", "Ticker: {ticker}\nTrade date: {trade_date}"),
            MessagesPlaceholder(variable_name="messages"),
        ])

        bound_llm = (
            llm.bind_tools(FUNDAMENTAL_TOOLS, tool_choice=FUNDAMENTAL_TOOLS[0].name)
            if not messages
            else llm.bind_tools(FUNDAMENTAL_TOOLS)
        )
        chain = prompt | bound_llm
        result = chain.invoke({
            "system_message": FUNDAMENTAL_SYSTEM_MESSAGE,
            "tool_names": ", ".join(tool.name for tool in FUNDAMENTAL_TOOLS),
            "ticker": ticker,
            "trade_date": trade_date,
            "messages": messages,
        })

        update = {"fundamental_messages": [result]}

        if not getattr(result, "tool_calls", None):
            report = result.content
            update["fundamental_report"] = report
            get_report_logger().log_fundamental_report(report, ticker, trade_date)

        return update

    return fundamental_analyst


def create_fundamental_tools_node():
    return ToolNode(FUNDAMENTAL_TOOLS, messages_key="fundamental_messages")
