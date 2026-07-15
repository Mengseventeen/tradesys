from tradesys.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Route an analyst either to its tools node or to the end of its branch."""

    def should_continue_analysis(self, state: AgentState, messages_key: str) -> str:
        messages = state.get(messages_key, [])
        if not messages:
            return "end"

        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"

        return "end"
