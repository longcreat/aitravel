from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agent.service import TravelAgentService
from app.auth.store import AuthSQLiteStore
from app.db.bootstrap import bootstrap_sqlite_database
from app.schemas.chat import ChatInvokeRequest


class _FakeAgent:
    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert context is not None
        assert context.user_id
        assert context.thread_id == "thread-1"
        assert context.locale == "zh-CN"
        assert context.model_profile_key == "standard"
        assert context.session_meta == {}
        assert config["configurable"]["llm_model"] == "test-standard-model"
        assert config["configurable"]["llm_model_provider"] == "openai"
        assert config["configurable"]["llm_temperature"] == 0.2
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
                            content="我先查一下当前时间，再帮你排顺序。",
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
                            content="我先查一下当前时间，再帮你排顺序。",
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
                        content="我先查一下当前时间，再帮你排顺序。",
                        tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}],
                    ),
                    ToolMessage(name="get_current_time", content="当前时间为21:02:21", tool_call_id="call-1"),
                    AIMessage(content="推荐先去东京，再去大阪。"),
                ],
            },
        }


class _NoTokenAgent:
    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert context is not None
        assert context.model_profile_key == "standard"
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        yield {
            "type": "values",
            "ns": (),
            "data": {
                "messages": [AIMessage(content="只返回最终答案")],
            },
        }


class _ReasoningAgent:
    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先分析需求。"}, id="chunk-r1"),
                {"langgraph_node": "model"},
            ),
        }
        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(content="给你一个推荐方案。", additional_kwargs={"reasoning_content": ""}, id="chunk-a1"),
                {"langgraph_node": "model"},
            ),
        }
        yield {
            "type": "values",
            "ns": (),
            "data": {
                "messages": [
                    AIMessage(
                        content="给你一个推荐方案。",
                        additional_kwargs={"reasoning_content": "先分析需求。"},
                    )
                ],
            },
        }


class _CaptureInputAgent:
    def __init__(self) -> None:
        self.calls: list[list] = []
        self.contexts: list[object] = []

    async def astream(self, payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        self.calls.append(list(payload["messages"]))
        assert config["configurable"]["llm_model"] == "test-standard-model"
        self.contexts.append(context)
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

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.runtime.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "test-thinking-model")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.6")

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", lambda **_kwargs: _FakeAgent())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
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
    assert detail.messages[1].meta is not None
    assert len(detail.messages[1].meta.tool_traces) == 2
    assert detail.messages[1].meta.tool_traces[0].phase == "called"
    assert detail.messages[1].meta.tool_traces[0].tool_name == "get_current_time"
    assert detail.messages[1].meta.tool_traces[0].payload == {}
    assert detail.messages[1].meta.tool_traces[1].phase == "returned"
    assert detail.messages[1].meta.tool_traces[1].tool_name == "get_current_time"
    assert detail.messages[1].meta.tool_traces[1].payload == "当前时间为21:02:21"
    assert len(detail.messages[1].meta.step_groups) == 1
    assert detail.messages[1].meta.step_groups[0].items[0].tool_name == "get current time"
    assert detail.messages[1].meta.step_groups[0].items[0].status == "success"
    assert detail.messages[1].meta.render_segments[0].type == "text"
    assert detail.messages[1].meta.render_segments[1].type == "step"
    assert detail.messages[1].meta.render_segments[2].type == "text"


@pytest.mark.asyncio
async def test_travel_agent_service_stream_invoke_without_token_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.runtime.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", lambda **_kwargs: _NoTokenAgent())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
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
async def test_travel_agent_service_persists_reasoning_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.runtime.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", lambda **_kwargs: _ReasoningAgent())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
    user = AuthSQLiteStore(sqlite_db).create_user("demo@example.com")
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-reasoning", user_message="帮我想一下方案", locale="zh-CN"),
    ):
        events.append((event_name, payload))

    assert events[0][0] == "messages"
    assert events[0][1]["data"][0]["data"]["additional_kwargs"]["reasoning_content"] == "先分析需求。"

    detail = service.get_session_detail(user.id, "thread-reasoning")
    assert detail is not None
    assert detail.messages[1].meta is not None
    assert detail.messages[1].text == "给你一个推荐方案。"
    assert detail.messages[1].meta.reasoning_text == "先分析需求。"
    assert detail.messages[1].meta.reasoning_state == "completed"


@pytest.mark.asyncio
async def test_travel_agent_service_uses_latest_human_message_as_agent_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    capture_agent = _CaptureInputAgent()

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.runtime.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", lambda **_kwargs: capture_agent)

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
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
    assert len(capture_agent.contexts) == 2
    assert capture_agent.contexts[0].user_id == user.id
    assert capture_agent.contexts[0].thread_id == "thread-3"
    assert capture_agent.contexts[0].locale == "zh-CN"
    assert capture_agent.contexts[0].model_profile_key == "standard"
    assert capture_agent.contexts[0].session_meta == {}
    assert capture_agent.contexts[1].user_id == user.id


@pytest.mark.asyncio
async def test_travel_agent_service_startup_uses_context_schema_and_middleware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    captured: dict[str, object] = {}

    def _fake_create_agent(**kwargs):
        captured.update(kwargs)
        return _NoTokenAgent()

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr("app.agent.runtime.build_chat_model", lambda: "fake-model")
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", _fake_create_agent)

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    assert captured["context_schema"].__name__ == "AgentRequestContext"
    middleware = captured["middleware"]
    assert isinstance(middleware, list)
    assert len(middleware) == 2
