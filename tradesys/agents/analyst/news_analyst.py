from langchain_core.messages import RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import ToolNode

from tradesys.agents.utils.agent_states import AgentState
from tradesys.agents.utils.news_data_tools import (
    get_news_data,
    get_news_on_date,
)
from tradesys.agents.utils.report_logger import get_report_logger


NEWS_TOOLS = [
    get_news_data,
    get_news_on_date,
]


NEWS_SYSTEM_MESSAGE = """
You are a news analyst tasked with analyzing company news over the recent
period ending on the trade date. Treat the trade date as the analysis cutoff
and do not use future information. Use the available tools to inspect company
news, especially the past week when data is available; let the tools provide
the articles and do not invent headlines or events.

Write a comprehensive, trader-facing report that identifies the most important
news items, groups related catalysts, explains likely market impact, separates
company-specific developments from broader market noise, and highlights
sentiment, timing, and risk. Provide specific, actionable insights with
supporting article evidence so traders can judge whether the news flow supports
buying, holding, or selling. If there is little or no relevant recent news, say
that clearly and explain how that affects conviction.

Final report format:
1. Key news
2. Catalyst and sentiment analysis
3. Market impact for traders
4. Key risks and unresolved questions
5. Final view: bullish, bearish, or neutral

Append a Markdown table at the end that organizes the key news items,
evidence, expected market impact, trading implication, and confidence/risk note.
"""


def _active_messages(messages):
    return [msg for msg in messages if not isinstance(msg, RemoveMessage)]


def create_news_analyst(llm):
    def news_analyst(state: AgentState) -> dict:
        ticker = state["ticker"]
        trade_date = state["trade_date"]
        messages = _active_messages(state.get("news_messages", []))

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_message}\nAvailable tools: {tool_names}"),
            ("user", "Ticker: {ticker}\nTrade date: {trade_date}"),
            MessagesPlaceholder(variable_name="messages"),
        ])

        chain = prompt | llm.bind_tools(NEWS_TOOLS)
        result = chain.invoke({
            "system_message": NEWS_SYSTEM_MESSAGE,
            "tool_names": ", ".join(tool.name for tool in NEWS_TOOLS),
            "ticker": ticker,
            "trade_date": trade_date,
            "messages": messages,
        })

        update = {"news_messages": [result]}

        if not getattr(result, "tool_calls", None):
            report = result.content
            update["news_report"] = report
            get_report_logger().log_news_report(report, ticker, trade_date)

        return update

    return news_analyst


def create_news_tools_node():
    return ToolNode(NEWS_TOOLS, messages_key="news_messages")
