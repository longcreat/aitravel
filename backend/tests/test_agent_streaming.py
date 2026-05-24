from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.agent.context import AgentRequestContext
from app.agent.streaming import (
    AgentStreamService,
    StreamRunState,
    _extract_tool_events,
    _serialize_stream_part,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal LangGraph-style stream emitters
# ---------------------------------------------------------------------------
#
# The new streaming architecture treats `messages` purely as a text/reasoning
# delta channel and relies on `updates` for tool lifecycle events. Each fake
# agent below mirrors what LangGraph 1.x actually emits in production:
#
#   * model node text token  →  ``messages`` AIMessageChunk(content="…")
#   * model node finishes    →  ``updates`` AIMessage(tool_calls=[...] | content)
#   * tool node finishes     →  ``updates`` ToolMessage(...)
#
# For brevity we elide the per-token tool_call_chunks entirely — they are
# explicitly ignored by the streaming layer in the new design.


class _WhitespaceChunkAgent:
    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert context is not None
        assert stream_mode == ["messages", "updates"]
        assert version == "v2"
        yield {
            "type": "messages",
            "data": (AIMessageChunk(content="你好 ", id="chunk-1"), {"langgraph_node": "model"}),
        }
        yield {
            "type": "messages",
            "data": (AIMessageChunk(content="世界", id="chunk-2"), {"langgraph_node": "model"}),
        }


class _FakeRuntimeService:
    def require_runtime(self):
        return type("Runtime", (), {"agent": _WhitespaceChunkAgent()})()


class _ToolCallAgent:
    """Real LangGraph emission shape:
        1. messages chunks for tool_call_chunks (ignored by streaming layer)
        2. updates: AIMessage with completed tool_calls (drives tool.start)
        3. updates: ToolMessage with execution result (drives tool.done)
    """

    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert stream_mode == ["messages", "updates"]
        # Streaming chunks of the tool call — present in real traffic but
        # deliberately ignored by the new streaming layer (no tool.start here).
        yield {
            "type": "messages",
            "data": (
                AIMessageChunk(
                    content="",
                    id="chunk-tool-1",
                    tool_call_chunks=[
                        {
                            "name": "maps_weather",
                            "args": '{"city":"杭州"}',
                            "id": "call-weather-1",
                            "index": 0,
                        }
                    ],
                ),
                {"langgraph_node": "model"},
            ),
        }
        # model node finishes -> AIMessage with completed tool_calls (this drives tool.start)
        yield {
            "type": "updates",
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            id="ai-msg-tool-1",
                            tool_calls=[
                                {
                                    "name": "maps_weather",
                                    "args": {"city": "杭州"},
                                    "id": "call-weather-1",
                                    "type": "tool_call",
                                }
                            ],
                        )
                    ]
                }
            },
        }
        # tool node finishes -> ToolMessage (drives tool.done)
        yield {
            "type": "updates",
            "data": {
                "tools": {
                    "messages": [
                        ToolMessage(
                            name="maps_weather",
                            content="杭州晴，26℃",
                            tool_call_id="call-weather-1",
                        )
                    ]
                }
            },
        }


class _ToolCallRuntimeService:
    def require_runtime(self):
        return type("Runtime", (), {"agent": _ToolCallAgent()})()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_serialize_stream_part_converts_langchain_messages() -> None:
    part = {
        "type": "messages",
        "data": (
            AIMessageChunk(content="你好", additional_kwargs={"reasoning_content": "先想一下。"}, id="chunk-1"),
            {"langgraph_node": "model"},
        ),
    }

    serialized = _serialize_stream_part(part)

    assert serialized["type"] == "messages"
    assert serialized["data"][0]["type"] == "AIMessageChunk"
    assert serialized["data"][0]["data"]["content"] == "你好"
    assert serialized["data"][0]["data"]["additional_kwargs"]["reasoning_content"] == "先想一下。"


@pytest.mark.asyncio
async def test_stream_agent_run_preserves_whitespace_for_tts_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    service = AgentStreamService(runtime_service=_FakeRuntimeService())
    state = StreamRunState()
    captured_chunks: list[str] = []

    async for _event_name, _payload in service.stream_agent_run(
        thread_id="thread-tts",
        agent_input={"messages": ["ignored"]},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=AgentRequestContext(
            user_id="user-1",
            thread_id="thread-tts",
            locale="zh-CN",
            model_profile_key="standard",
            session_meta={},
        ),
        on_assistant_text_chunk=captured_chunks.append,
    ):
        pass

    assert "".join(captured_chunks) == "你好 世界"


@pytest.mark.asyncio
async def test_stream_agent_run_emits_one_tool_start_and_one_tool_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single tool call should produce exactly one tool.start and one tool.done.

    Previously the streaming layer additionally tried to emit tool.start from
    `messages` tool_call_chunks, which collided with the canonical updates path
    and produced N+1 spurious tool.start events that kept the UI spinning. The
    new design routes tool lifecycle exclusively through `updates`, so this
    test guards against regressions of that bug.
    """
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    service = AgentStreamService(runtime_service=_ToolCallRuntimeService())
    state = StreamRunState()
    events: list[tuple[str, dict]] = []

    async for event_name, payload in service.stream_agent_run(
        thread_id="thread-tool-first",
        agent_input={"messages": ["ignored"]},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=AgentRequestContext(
            user_id="user-1",
            thread_id="thread-tool-first",
            locale="zh-CN",
            model_profile_key="standard",
            session_meta={},
        ),
    ):
        events.append((event_name, payload))

    tool_events = [(name, p) for name, p in events if name.startswith("tool.")]
    assert [name for name, _ in tool_events] == ["tool.start", "tool.done"]

    start_part = tool_events[0][1]["part"]
    done_part = tool_events[1][1]["part"]
    assert start_part["status"] == "running"
    assert start_part["tool_name"] == "maps_weather"
    assert start_part["input"] == {"city": "杭州"}  # complete dict from updates, no partial JSON
    assert done_part["status"] == "success"
    assert done_part["output"] == "杭州晴，26℃"
    assert [part.type for part in state.ui_parts] == ["tool"]


def test_extract_tool_events_prefers_tool_artifact_for_payload() -> None:
    events = list(
        _extract_tool_events(
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            name="exa_web_search_advanced_exa",
                            content="Exa 高级搜索找到 1 条结果。",
                            artifact={"kind": "exa_search", "results": [{"title": "Official Guide"}]},
                            tool_call_id="call-exa-1",
                        )
                    ]
                }
            },
            seen_called=set(),
            seen_returned=set(),
        )
    )

    assert len(events) == 1
    event_name, event_payload, trace = events[0]
    assert event_name == "tool_returned"
    assert event_payload == {
        "tool_name": "exa_web_search_advanced_exa",
        "payload": "Exa 高级搜索找到 1 条结果。",
    }
    assert trace.payload == {"kind": "exa_search", "results": [{"title": "Official Guide"}]}


class _HotelToolAgent:
    """Streams the canonical model→tools update sequence with a hotel artifact.

    Verifies that ``ChatToolPart.cards`` is populated by the structured card
    extractor when the underlying tool returns a recognisable payload.
    """

    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert stream_mode == ["messages", "updates"]
        # model node finishes — drives tool.start
        yield {
            "type": "updates",
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            id="ai-msg-hotel-1",
                            tool_calls=[
                                {
                                    "name": "rollinggo-hotel_searchHotels",
                                    "args": {"city": "成都"},
                                    "id": "call-hotel-1",
                                    "type": "tool_call",
                                }
                            ],
                        )
                    ]
                }
            },
        }
        # tools node finishes — drives tool.done with cards extracted
        yield {
            "type": "updates",
            "data": {
                "tools": {
                    "messages": [
                        ToolMessage(
                            name="rollinggo-hotel_searchHotels",
                            content="找到 2 家酒店",
                            artifact=[
                                {
                                    "hotelName": "桔子酒店",
                                    "address": "东胜街1号",
                                    "price": {"hasPrice": True, "lowestPrice": 277, "currency": "CNY"},
                                    "starLevel": 3,
                                    "bookingUrl": "https://example.com/booking/1",
                                },
                                {
                                    "hotelName": "海友酒店",
                                    "location": "锦江区",
                                    "price": {"hasPrice": True, "lowestPrice": 292, "currency": "CNY"},
                                    "bookingUrl": "https://example.com/booking/2",
                                },
                            ],
                            tool_call_id="call-hotel-1",
                        )
                    ]
                }
            },
        }


class _HotelToolRuntimeService:
    def require_runtime(self):
        return type("Runtime", (), {"agent": _HotelToolAgent()})()


@pytest.mark.asyncio
async def test_stream_agent_run_attaches_structured_cards_to_tool_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hotel-list payload should be parsed into typed cards on the tool part."""
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    service = AgentStreamService(runtime_service=_HotelToolRuntimeService())
    state = StreamRunState()
    events: list[tuple[str, dict]] = []

    async for event_name, payload in service.stream_agent_run(
        thread_id="thread-hotel-cards",
        agent_input={"messages": ["ignored"]},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=AgentRequestContext(
            user_id="user-1",
            thread_id="thread-hotel-cards",
            locale="zh-CN",
            model_profile_key="standard",
            session_meta={},
        ),
    ):
        events.append((event_name, payload))

    # Exactly tool.start then tool.done
    assert [event_name for event_name, _ in events] == ["tool.start", "tool.done"]
    started, finished = events
    # tool.start carries no cards yet; tool.done carries them
    assert started[1]["part"]["cards"] == []
    cards = finished[1]["part"]["cards"]
    assert len(cards) == 2
    assert cards[0]["card_type"] == "hotel"
    assert cards[0]["data"]["name"] == "桔子酒店"
    assert cards[0]["data"]["price"] == 277.0
    assert cards[0]["source_tool_call_id"] == "call-hotel-1"
    assert cards[1]["data"]["name"] == "海友酒店"

    tool_part = next(part for part in state.ui_parts if part.type == "tool")
    assert len(tool_part.cards) == 2  # type: ignore[union-attr]
    assert tool_part.cards[0].card_type == "hotel"  # type: ignore[union-attr]
