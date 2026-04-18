from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.checkpoints import _messages_have_closed_tool_calls


def test_messages_have_closed_tool_calls() -> None:
    assert _messages_have_closed_tool_calls(
        [
            HumanMessage(content="查天气"),
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}]),
            ToolMessage(name="get_current_time", content="{}", tool_call_id="call-1"),
            AIMessage(content="现在是晚上九点"),
        ]
    )

    assert not _messages_have_closed_tool_calls(
        [
            HumanMessage(content="查天气"),
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}]),
            HumanMessage(content="继续"),
        ]
    )
