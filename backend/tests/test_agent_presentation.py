from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agent.presentation import (
    _content_to_text,
    _message_reasoning_text,
    build_final_response,
)


def test_content_to_text_skips_reasoning_blocks() -> None:
    content = [
        {"type": "reasoning", "reasoning": "先分析"},
        {"type": "text", "text": "最终回答"},
    ]

    assert _content_to_text(content) == "最终回答"


def test_message_reasoning_text_prefers_additional_kwargs() -> None:
    message = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先分析需求。"})

    assert _message_reasoning_text(message) == "先分析需求。"


def test_build_final_response_rebuilds_steps_and_reasoning() -> None:
    runtime = SimpleNamespace(mcp_bundle=SimpleNamespace(connected_servers=["demo"], errors=[]))
    latest_values = {
        "messages": [
            HumanMessage(content="帮我规划日本行程"),
            AIMessage(
                content="我先查一下天气。",
                additional_kwargs={"reasoning_content": "先确认天气和城市顺序。"},
                tool_calls=[{"id": "call-1", "name": "weather_lookup", "args": {"city": "Tokyo"}}],
            ),
            ToolMessage(name="weather_lookup", content="sunny", tool_call_id="call-1"),
            AIMessage(content="推荐先去东京。"),
        ]
    }

    response = build_final_response(
        latest_values=latest_values,
        accumulated_chunk=None,
        streamed_tool_traces=[],
        runtime=runtime,
    )

    assert response.assistant_message == "我先查一下天气。推荐先去东京。"
    assert response.meta.reasoning_text == "先确认天气和城市顺序。"
    assert response.meta.reasoning_state == "completed"
    assert len(response.meta.tool_traces) == 2
    assert len(response.meta.step_groups) == 1
    assert response.meta.step_groups[0].items[0].tool_name == "weather lookup"
    assert response.meta.step_groups[0].items[0].status == "success"


def test_build_final_response_prefers_tool_artifact_for_trace_payload() -> None:
    runtime = SimpleNamespace(mcp_bundle=SimpleNamespace(connected_servers=[], errors=[]))
    latest_values = {
        "messages": [
            HumanMessage(content="帮我查京都攻略"),
            AIMessage(
                content="我先用 Exa 搜索一下。",
                tool_calls=[{"id": "call-exa-1", "name": "exa_web_search_advanced_exa", "args": {"query": "京都攻略"}}],
            ),
            ToolMessage(
                name="exa_web_search_advanced_exa",
                content="Exa 高级搜索找到 1 条结果。",
                artifact={"kind": "exa_search", "results": [{"title": "Kyoto Guide"}]},
                tool_call_id="call-exa-1",
            ),
            AIMessage(content="我找到一篇京都官方攻略。"),
        ]
    }

    response = build_final_response(
        latest_values=latest_values,
        accumulated_chunk=None,
        streamed_tool_traces=[],
        runtime=runtime,
    )

    assert response.meta.tool_traces[1].payload == {
        "kind": "exa_search",
        "results": [{"title": "Kyoto Guide"}],
    }
