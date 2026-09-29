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
# Fixtures: minimal LangGraph-style v3 protocol stream emitters
# ---------------------------------------------------------------------------
#
# The v3 streaming architecture consumes raw protocol events from
# `astream_events(version="v3")`:
#
#   * model node text token  →  `messages` channel content-block-delta (text-delta)
#   * model node finishes    →  `values` snapshot with AIMessage(tool_calls) / content
#   * tool node finishes     →  `values` snapshot with ToolMessage(...)
#
# For brevity we elide tool-call content blocks on the messages channel — they
# are explicitly ignored by the streaming layer in the new design.


def _text_delta_event(text: str) -> dict:
    return {
        "method": "messages",
        "params": {
            "data": [
                {
                    "event": "content-block-delta",
                    "index": 0,
                    "delta": {"type": "text-delta", "text": text},
                }
            ]
        },
    }


def _values_event(data: dict) -> dict:
    return {"method": "values", "params": {"data": data}}


class _WhitespaceChunkAgent:
    async def astream_events(self, _payload, config=None, context=None, version=None):
        assert config is not None
        assert context is not None
        assert version == "v3"

        async def _run():
            yield _text_delta_event("你好 ")
            yield _text_delta_event("世界")

        return _run()


class _FakeRuntimeService:
    def require_runtime(self):
        return type("Runtime", (), {"agent": _WhitespaceChunkAgent()})()


class _ToolCallAgent:
    """Real LangGraph v3 emission shape:
        1. messages channel: tool-call content blocks (ignored by streaming layer)
        2. values snapshot: AIMessage with completed tool_calls (drives tool.start)
        3. values snapshot: ToolMessage with execution result (drives tool.done)
    """

    async def astream_events(self, _payload, config=None, context=None, version=None):
        assert version == "v3"

        async def _run():
            # Streaming tool-call blocks — present in real traffic but
            # deliberately ignored by the streaming layer (no tool.start here).
            yield {
                "method": "messages",
                "params": {
                    "data": [
                        {
                            "event": "content-block-start",
                            "index": 0,
                            "block": {"type": "tool_call", "name": "maps_weather"},
                        }
                    ]
                },
            }
            # model node finishes -> values snapshot with AIMessage (drives tool.start)
            yield _values_event(
                {
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
                }
            )
            # tool node finishes -> values snapshot with ToolMessage (drives tool.done)
            yield _values_event(
                {
                    "tools": {
                        "messages": [
                            ToolMessage(
                                name="maps_weather",
                                content="杭州晴，26℃",
                                tool_call_id="call-weather-1",
                            )
                        ]
                    }
                }
            )

        return _run()


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


def _reasoning_delta_event(text: str) -> dict:
    return {
        "method": "messages",
        "params": {
            "data": [
                {
                    "event": "content-block-delta",
                    "index": 0,
                    "delta": {"type": "reasoning-delta", "reasoning": text},
                }
            ]
        },
    }


class _MultiSuperstepAgent:
    """两轮模型调用 + 一次工具执行的完整 v3 事件序列。

    轮1: 思考增量 → 正文增量（触发 reasoning→text 切换 sealing）
    轮2: 工具执行（values 快照驱动 tool.start/tool.done）
    轮3: 思考增量 → 正文增量（工具后新开 part）
    """

    async def astream_events(self, _payload, config=None, context=None, version=None):
        assert version == "v3"

        async def _run():
            yield _reasoning_delta_event("先想")
            yield _reasoning_delta_event("一下。")
            yield _text_delta_event("我先查")
            yield _values_event(
                {
                    "model": {
                        "messages": [
                            AIMessage(
                                content="我先查",
                                tool_calls=[
                                    {
                                        "name": "maps_weather",
                                        "args": {"city": "杭州"},
                                        "id": "call-ms-1",
                                        "type": "tool_call",
                                    }
                                ],
                            )
                        ]
                    }
                }
            )
            yield _values_event(
                {
                    "tools": {
                        "messages": [
                            ToolMessage(name="maps_weather", content="杭州晴", tool_call_id="call-ms-1")
                        ]
                    }
                }
            )
            yield _reasoning_delta_event("查到了。")
            yield _text_delta_event("杭州晴，26℃。")

        return _run()


@pytest.mark.asyncio
async def test_stream_multi_superstep_part_ordering_and_accumulation() -> None:
    """多轮调用下：part 按类型切换正确 seal、工具事件各一次、累计文本/思考完整。"""
    service = AgentStreamService(runtime_service=_FakeRuntimeServiceOf(_MultiSuperstepAgent()))
    state = StreamRunState()
    tts_chunks: list[str] = []
    events: list[tuple[str, dict]] = []

    async for event_name, payload in service.stream_agent_run(
        thread_id="thread-multi",
        agent_input={"messages": ["ignored"]},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=AgentRequestContext(
            user_id="user-1",
            thread_id="thread-multi",
            model_profile_key="standard",
            session_meta={},
        ),
        on_assistant_text_chunk=tts_chunks.append,
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    # 事件骨架：reasoning → seal → text → seal → tool.start → tool.done → reasoning → seal → text
    assert names == [
        "part.delta",  # reasoning "先想"
        "part.delta",  # reasoning "一下。"
        "part.delta",  # seal reasoning-1
        "part.delta",  # text "我先查"
        "part.delta",  # seal text-1（工具来临前收尾）
        "tool.start",
        "tool.done",
        "part.delta",  # reasoning "查到了。"（工具后新开 reasoning part）
        "part.delta",  # seal reasoning-2
        "part.delta",  # text "杭州晴，26℃。"
    ]

    # part 序列与状态
    assert [(p.type, p.text) for p in state.ui_parts if p.type in {"reasoning", "text"}] == [
        ("reasoning", "先想一下。"),
        ("text", "我先查"),
        ("reasoning", "查到了。"),
        ("text", "杭州晴，26℃。"),
    ]
    assert [p.status for p in state.ui_parts if p.type in {"reasoning", "text"}] == [
        "completed",
        "completed",
        "completed",
        "streaming",  # 最后一段正文尚未被显式收尾（message.completed 时由 service 收尾）
    ]

    # 累计语义（build_final_response 的数据源）
    assert state.assistant_text == "我先查杭州晴，26℃。"
    assert state.reasoning_text == "先想一下。查到了。"

    # TTS 逐字流只含可见文本，含空白、无思考内容
    assert "".join(tts_chunks) == "我先查杭州晴，26℃。"

    # 工具事件恰好一次 start / 一次 done
    assert names.count("tool.start") == 1
    assert names.count("tool.done") == 1


def _FakeRuntimeServiceOf(agent):
    return type("RuntimeService", (), {"require_runtime": lambda self: type("Runtime", (), {"agent": agent})()})()


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
    """Streams the canonical model→tools values-snapshot sequence with a hotel artifact.

    Verifies that ``ChatToolPart.cards`` is populated by the structured card
    extractor when the underlying tool returns a recognisable payload.
    """

    async def astream_events(self, _payload, config=None, context=None, version=None):
        assert version == "v3"

        async def _run():
            # model node finishes — drives tool.start
            yield _values_event(
                {
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
                }
            )
            # tools node finishes — drives tool.done with cards extracted
            yield _values_event(
                {
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
                }
            )

        return _run()


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
