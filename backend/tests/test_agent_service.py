from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agent.service import TravelAgentService, _messages_have_closed_tool_calls
from app.auth.store import AuthSQLiteStore
from app.schemas.chat import ChatInvokeRequest


class _FakeAgent:
    async def astream(self, _payload, config=None, stream_mode=None, version=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        assert _payload == {"messages": [HumanMessage(content="帮我规划日本行程")]}

        yield {
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="推荐先去东京，", id="chunk-1"), {"langgraph_node": "model"}),
        }
        yield {
            "type": "messages",
            "ns": (),
            "data": (AIMessageChunk(content="再去大阪。", id="chunk-2"), {"langgraph_node": "model"}),
        }

        # 人工重复一遍 tool_called / tool_returned 事件，验证服务层去重能力。
        yield {
            "type": "updates",
            "ns": (),
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            content="我先调用预算工具。",
                            tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}],
                        )
                    ]
                }
            },
        }
        yield {
            "type": "updates",
            "ns": (),
            "data": {
                "model": {
                    "messages": [
                        AIMessage(
                            content="我先调用预算工具。",
                            tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}],
                        )
                    ]
                }
            },
        }
        yield {
            "type": "updates",
            "ns": (),
            "data": {
                "tools": {
                    "messages": [ToolMessage(name="get_current_time", content="当前时间为21:02:21", tool_call_id="call-1")]
                }
            },
        }
        yield {
            "type": "updates",
            "ns": (),
            "data": {
                "tools": {
                    "messages": [ToolMessage(name="get_current_time", content="当前时间为21:02:21", tool_call_id="call-1")]
                }
            },
        }

        yield {
            "type": "values",
            "ns": (),
            "data": {
                "messages": [
                    AIMessage(
                        content="推荐先去东京，再去大阪。",
                        tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}],
                    ),
                    ToolMessage(name="get_current_time", content="当前时间为21:02:21", tool_call_id="call-1"),
                    AIMessage(content="推荐先去东京，再去大阪。"),
                ],
            },
        }


class _NoTokenAgent:
    async def astream(self, _payload, config=None, stream_mode=None, version=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        yield {
            "type": "values",
            "ns": (),
            "data": {
                "messages": [AIMessage(content="只返回最终答案")],
            },
        }


class _CaptureInputAgent:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def astream(self, payload, config=None, stream_mode=None, version=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        self.calls.append(list(payload["messages"]))
        yield {
            "type": "values",
            "ns": (),
            "data": {
                "messages": [AIMessage(content="收到")],
            },
        }


class _DummyCheckpointer:
    def __init__(self) -> None:
        self.deleted_threads: list[str] = []
        self.lock = asyncio.Lock()
        self.conn = None

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)

    async def alist(self, _config, limit=None):
        if False:
            yield None
        return

    async def setup(self) -> None:
        return None


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
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: _FakeAgent())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    user = AuthSQLiteStore(sqlite_db).create_user("demo@example.com")
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-1", user_message="帮我规划日本行程", locale="zh-CN")
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == ["messages", "messages", "updates", "updates", "updates", "updates", "values"]
    assert events[0][1]["type"] == "messages"
    assert events[0][1]["data"][0]["type"] == "AIMessageChunk"
    assert events[0][1]["data"][0]["data"]["content"] == "推荐先去东京，"
    assert events[-1][1]["type"] == "values"
    assert events[-1][1]["data"]["messages"][-1]["data"]["content"] == "推荐先去东京，再去大阪。"

    detail = service.get_session_detail(user.id, "thread-1")
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
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: _NoTokenAgent())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    user = AuthSQLiteStore(sqlite_db).create_user("demo@example.com")
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-2", user_message="直接给结果", locale="zh-CN")
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == ["values"]
    assert events[0][1]["data"]["messages"][0]["data"]["content"] == "只返回最终答案"


@pytest.mark.asyncio
async def test_travel_agent_service_uses_latest_human_message_as_agent_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    capture_agent = _CaptureInputAgent()

    monkeypatch.setattr("app.agent.service.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.service.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.service.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.service.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.service.create_agent", lambda **_kwargs: capture_agent)

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    user = AuthSQLiteStore(sqlite_db).create_user("demo@example.com")
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    async for _event_name, _payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-3", user_message="第一句", locale="zh-CN")
    ):
        pass

    async for _event_name, _payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-3", user_message="第二句", locale="zh-CN")
    ):
        pass

    assert len(capture_agent.calls) == 2
    assert len(capture_agent.calls[0]) == 1
    assert isinstance(capture_agent.calls[0][0], HumanMessage)
    assert capture_agent.calls[0][0].content == "第一句"
    assert len(capture_agent.calls[1]) == 1
    assert isinstance(capture_agent.calls[1][0], HumanMessage)
    assert capture_agent.calls[1][0].content == "第二句"


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
