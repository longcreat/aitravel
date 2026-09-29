from __future__ import annotations

from types import SimpleNamespace



from app.agent.presentation import (
    _content_to_text,
    build_final_response,
)


def test_content_to_text_skips_reasoning_blocks() -> None:
    content = [
        {"type": "reasoning", "reasoning": "先分析"},
        {"type": "text", "text": "最终回答"},
    ]

    assert _content_to_text(content) == "最终回答"


def test_build_final_response_uses_chunk_reasoning_and_traces() -> None:
    runtime = SimpleNamespace(mcp_bundle=SimpleNamespace(connected_servers=["demo"], errors=[]))

    response = build_final_response(
        assistant_text="我先查一下天气。推荐先去东京。",
        reasoning_text="先确认天气和城市顺序。",
        streamed_tool_traces=[
            {"phase": "called", "tool_name": "weather_lookup", "payload": {"city": "Tokyo"}, "tool_call_id": "call-1"},
            {"phase": "returned", "tool_name": "weather_lookup", "payload": "sunny", "tool_call_id": "call-1", "result_status": "success"},
        ],
        runtime=runtime,
    )

    assert response.assistant_message == "我先查一下天气。推荐先去东京。"
    assert response.meta.reasoning_text == "先确认天气和城市顺序。"
    assert response.meta.reasoning_state == "completed"
    assert len(response.meta.tool_traces) == 2


def test_build_final_response_prefers_tool_artifact_for_trace_payload() -> None:
    runtime = SimpleNamespace(mcp_bundle=SimpleNamespace(connected_servers=[], errors=[]))
    response = build_final_response(
        assistant_text="我先用 Exa 搜索一下。我找到一篇京都官方攻略。",
        reasoning_text="",
        streamed_tool_traces=[
            {"phase": "called", "tool_name": "exa_web_search_advanced_exa", "payload": {"query": "京都攻略"}, "tool_call_id": "call-exa-1"},
            {
                "phase": "returned",
                "tool_name": "exa_web_search_advanced_exa",
                "payload": {"kind": "exa_search", "results": [{"title": "Kyoto Guide"}]},
                "tool_call_id": "call-exa-1",
                "result_status": "success",
            },
        ],
        runtime=runtime,
    )

    assert response.meta.tool_traces[1].payload == {
        "kind": "exa_search",
        "results": [{"title": "Kyoto Guide"}],
    }
