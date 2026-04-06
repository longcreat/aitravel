from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agent.service import TravelAgentService
from app.schemas.chat import ChatInvokeRequest, StructuredTravelPlan


class _FakeGraph:
    async def astream(self, _payload, config=None, stream_mode=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]

        yield "messages", (AIMessageChunk(content="推荐先去东京，", id="chunk-1"), {"langgraph_node": "model"})
        yield "messages", (AIMessageChunk(content="再去大阪。", id="chunk-2"), {"langgraph_node": "model"})

        # 人工重复一遍 tool_called / tool_returned 事件，验证服务层去重能力。
        yield "updates", {
            "model": {
                "messages": [
                    AIMessage(
                        content="我先调用预算工具。",
                        tool_calls=[{"id": "call-1", "name": "estimate_trip_budget", "args": {"days": 3, "travelers": 2}}],
                    )
                ]
            }
        }
        yield "updates", {
            "model": {
                "messages": [
                    AIMessage(
                        content="我先调用预算工具。",
                        tool_calls=[{"id": "call-1", "name": "estimate_trip_budget", "args": {"days": 3, "travelers": 2}}],
                    )
                ]
            }
        }
        yield "updates", {
            "tools": {
                "messages": [ToolMessage(name="estimate_trip_budget", content="预算约5400元", tool_call_id="call-1")]
            }
        }
        yield "updates", {
            "tools": {
                "messages": [ToolMessage(name="estimate_trip_budget", content="预算约5400元", tool_call_id="call-1")]
            }
        }

        yield "values", {
            "messages": [
                AIMessage(
                    content="推荐先去东京，再去大阪。",
                    tool_calls=[{"id": "call-1", "name": "estimate_trip_budget", "args": {"days": 3, "travelers": 2}}],
                ),
                ToolMessage(name="estimate_trip_budget", content="预算约5400元", tool_call_id="call-1"),
                AIMessage(content="推荐先去东京，再去大阪。"),
            ],
            "structured_response": StructuredTravelPlan(
                summary="6天日本双城轻松线",
                itinerary=[{"day": 1, "city": "Tokyo", "activities": ["浅草寺", "上野公园"]}],
                followups=["你更偏好购物还是美食？"],
            ),
        }


class _NoTokenGraph:
    async def astream(self, _payload, config=None, stream_mode=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        yield "values", {
            "messages": [AIMessage(content="只返回最终答案")],
            "structured_response": StructuredTravelPlan(
                summary="只返回最终答案",
                itinerary=[],
                followups=[],
            ),
        }


class _CaptureInputGraph:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def astream(self, payload, config=None, stream_mode=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        self.calls.append(list(payload["messages"]))
        yield "values", {
            "messages": [AIMessage(content="收到")],
            "structured_response": StructuredTravelPlan(summary="收到", itinerary=[], followups=[]),
        }


class _DummyCheckpointer:
    def __init__(self) -> None:
        self.deleted_threads: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)


@pytest.mark.asyncio
async def test_travel_agent_service_stream_invoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.service.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.service.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.service.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.service.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: _FakeGraph())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        ChatInvokeRequest(thread_id="thread-1", user_message="帮我规划日本行程", locale="zh-CN")
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == ["start", "token", "token", "tool_called", "tool_returned", "final"]
    assert events[1][1]["chunk"]["content"] == "推荐先去东京，"
    assert events[1][1]["meta"]["node"] == "model"
    assert events[1][1]["meta"]["sequence"] == 1
    assert "delta" not in events[1][1]
    assert events[2][1]["chunk"]["content"] == "再去大阪。"
    assert events[3][1]["tool_name"] == "estimate_trip_budget"
    assert events[4][1]["tool_name"] == "estimate_trip_budget"
    assert events[5][1]["assistant_message"] == "推荐先去东京，再去大阪。"
    assert events[5][1]["itinerary"][0]["city"] == "Tokyo"

    detail = service.get_session_detail("thread-1")
    assert detail is not None
    assert detail.title.startswith("帮我规划日本行程")
    assert len(detail.messages) == 2
    assert detail.messages[0].role == "user"
    assert detail.messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_travel_agent_service_stream_invoke_without_token_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.service.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.service.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.service.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.service.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: _NoTokenGraph())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        ChatInvokeRequest(thread_id="thread-2", user_message="直接给结果", locale="zh-CN")
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == ["start", "final"]
    assert events[1][1]["assistant_message"] == "只返回最终答案"


@pytest.mark.asyncio
async def test_travel_agent_service_uses_latest_human_message_as_graph_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    capture_graph = _CaptureInputGraph()

    monkeypatch.setattr("app.agent.service.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.service.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.service.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.service.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: capture_graph)

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    async for _event_name, _payload in service.stream_invoke(
        ChatInvokeRequest(thread_id="thread-3", user_message="第一句", locale="zh-CN")
    ):
        pass

    async for _event_name, _payload in service.stream_invoke(
        ChatInvokeRequest(thread_id="thread-3", user_message="第二句", locale="zh-CN")
    ):
        pass

    assert len(capture_graph.calls) == 2
    assert len(capture_graph.calls[0]) == 1
    assert isinstance(capture_graph.calls[0][0], HumanMessage)
    assert capture_graph.calls[0][0].content == "第一句"
    assert len(capture_graph.calls[1]) == 1
    assert isinstance(capture_graph.calls[1][0], HumanMessage)
    assert capture_graph.calls[1][0].content == "第二句"
