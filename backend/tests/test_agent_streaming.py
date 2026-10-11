"""AgentStreamService 集成测试：真实 create_agent + fake 模型 + 真实工具。

不再手工模拟协议事件——直接跑一个真图，验证 typed projections 消费管线
产出的 SSE 事件契约（part.delta / tool.start / tool.done）与状态累计语义。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.agent.context import AgentRequestContext
from app.agent.streaming import AgentStreamService, StreamRunState


class _RuntimeService:
    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def require_runtime(self):
        return type("Runtime", (), {"agent": self._agent})()


class _FakeChatModel(FakeMessagesListChatModel):
    """按序回放消息的假模型；create_agent 需要 bind_tools 能力。"""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_FakeChatModel":
        return self


def _agent_for(responses: list[AIMessage], tools: list | None = None):
    model = _FakeChatModel(responses=responses)
    return create_agent(model=model, tools=tools or [], context_schema=AgentRequestContext)


def _context(thread_id: str) -> AgentRequestContext:
    return AgentRequestContext(
        user_id="user-1",
        thread_id=thread_id,
        locale="zh-CN",
        model_profile_key="standard",
        session_meta={},
    )


async def _collect(service: AgentStreamService, agent: Any, thread_id: str):
    state = StreamRunState()
    tts: list[str] = []
    events: list[tuple[str, dict]] = []
    async for name, payload in service.stream_agent_run(
        thread_id=thread_id,
        agent_input={"messages": []},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=_context(thread_id),
        on_assistant_text_chunk=tts.append,
        agent=agent,
    ):
        events.append((name, payload))
    return state, tts, events


@pytest.mark.asyncio
async def test_text_streaming_accumulates_and_feeds_tts() -> None:
    agent = _agent_for([AIMessage(content="你好 世界")])
    service = AgentStreamService(runtime_service=_RuntimeService(agent))

    state, tts, events = await _collect(service, agent, "t-text")

    assert [name for name, _ in events] == ["part.delta"]
    assert events[0][1]["text_delta"] == "你好 世界"
    assert state.assistant_text == "你好 世界"
    assert "".join(tts) == "你好 世界"


@pytest.mark.asyncio
async def test_reasoning_and_text_parts_are_separate() -> None:
    agent = _agent_for(
        [
            AIMessage(
                content=[
                    {"type": "reasoning", "reasoning": "先想一下。"},
                    {"type": "text", "text": "答案是 42。"},
                ]
            )
        ]
    )
    service = AgentStreamService(runtime_service=_RuntimeService(agent))

    state, tts, events = await _collect(service, agent, "t-reason")

    kinds = [(p["part_type"], p["text_delta"]) for _name, p in events if p.get("text_delta")]
    assert ("reasoning", "先想一下。") in kinds
    assert ("text", "答案是 42。") in kinds
    assert state.reasoning_text == "先想一下。"
    assert state.assistant_text == "答案是 42。"
    # TTS 只拿可见文本
    assert "".join(tts) == "答案是 42。"


@tool
def maps_weather(city: str) -> str:
    """查询城市天气。"""
    return "杭州晴，26℃"


@pytest.mark.asyncio
async def test_tool_lifecycle_emits_one_start_one_done() -> None:
    agent = _agent_for(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "maps_weather", "args": {"city": "杭州"}, "id": "call-w1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="杭州晴，26℃，适合出行。"),
        ],
        tools=[maps_weather],
    )
    service = AgentStreamService(runtime_service=_RuntimeService(agent))

    state, _tts, events = await _collect(service, agent, "t-tool")

    names = [name for name, _ in events]
    assert names.count("tool.start") == 1
    assert names.count("tool.done") == 1
    start = next(p for n, p in events if n == "tool.start")["part"]
    done = next(p for n, p in events if n == "tool.done")["part"]
    assert start["status"] == "running"
    assert start["tool_name"] == "maps_weather"
    assert start["input"] == {"city": "杭州"}
    assert done["status"] == "success"
    assert done["output"] == "杭州晴，26℃"
    # 工具前的文本 part 被收尾
    assert state.streamed_tool_traces[0].phase == "called"
    assert state.streamed_tool_traces[1].phase == "returned"


@tool
def rollinggo_hotel_search(city: str) -> Any:
    """搜索酒店。"""
    return [
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
    ]


@pytest.mark.asyncio
async def test_structured_cards_attached_from_final_state() -> None:
    agent = _agent_for(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "rollinggo_hotel_search",
                        "args": {"city": "成都"},
                        "id": "call-h1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="给你挑了两家。"),
        ],
        tools=[rollinggo_hotel_search],
    )
    service = AgentStreamService(runtime_service=_RuntimeService(agent))

    state, _tts, events = await _collect(service, agent, "t-cards")

    tool_part = next(p for p in state.ui_parts if p.type == "tool")
    assert tool_part.cards is not None and len(tool_part.cards) == 2
    assert tool_part.cards[0].card_type == "hotel"
    assert tool_part.cards[0].data["name"] == "桔子酒店"
    # 引用来源也从最终状态补齐
    assert tool_part.sources and tool_part.sources[0].url == "https://example.com/booking/1"
    assert state.citation_sources


@tool
def broken_tool(query: str) -> str:
    """总是失败的工具。"""
    raise ValueError("boom")


@pytest.mark.asyncio
async def test_tool_error_surfaces_as_error_status() -> None:
    from langchain.agents.middleware import ToolErrorMiddleware

    model = _FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "broken_tool", "args": {"query": "x"}, "id": "call-b1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="工具坏了，抱歉。"),
        ]
    )
    agent = create_agent(
        model=model,
        tools=[broken_tool],
        context_schema=AgentRequestContext,
        middleware=[ToolErrorMiddleware(on_error=lambda exc, request: f"工具执行失败：{exc}")],
    )
    service = AgentStreamService(runtime_service=_RuntimeService(agent))

    state, _tts, events = await _collect(service, agent, "t-err")

    done = next(p for n, p in events if n == "tool.done")["part"]
    assert done["status"] == "error"
    assert state.streamed_tool_traces[-1].result_status == "error"
