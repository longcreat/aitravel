from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.agent.context import AgentRequestContext
from app.agent.service import TravelAgentService
from app.auth.store import AuthSQLiteStore
from app.db.bootstrap import bootstrap_sqlite_database
from app.schemas.chat import ChatInvokeRequest


class _FakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> "_FakeChatModel":
        return self


@tool
def get_current_time() -> str:
    """返回当前时间。"""
    return "当前时间为21:02:21"


class _CaptureMiddleware(AgentMiddleware):
    """记录每次模型调用的输入消息与运行时上下文。"""

    def __init__(self, sink: list[dict]) -> None:
        super().__init__()
        self._sink = sink

    def wrap_model_call(self, request, handler):
        self._sink.append(
            {
                "messages": list(request.messages),
                "context": request.runtime.context if request.runtime else None,
            }
        )
        return handler(request)

    async def awrap_model_call(self, request, handler):
        self._sink.append(
            {
                "messages": list(request.messages),
                "context": request.runtime.context if request.runtime else None,
            }
        )
        return await handler(request)


def _agent(responses: list[AIMessage], *, tools: list | None = None, capture: list | None = None):
    middleware = [_CaptureMiddleware(capture)] if capture is not None else []
    return create_agent(
        model=_FakeChatModel(responses=responses),
        tools=tools or [],
        context_schema=AgentRequestContext,
        middleware=middleware,
    )


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


async def _make_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent_factory):
    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    monkeypatch.setattr(
        "app.agent.runtime.build_chat_models_by_profile",
        lambda: {"standard": "fake-model", "thinking": "fake-thinking-model"},
    )
    dummy_checkpointer = _DummyCheckpointer()
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", lambda **_kwargs: agent_factory())

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
    user = AuthSQLiteStore(sqlite_db).create_user("demo@example.com")
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()
    return service, user


@pytest.mark.asyncio
async def test_travel_agent_service_stream_invoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def factory():
        return _agent(
            [
                AIMessage(
                    content="我先查一下当前时间，再帮你排顺序。",
                    tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}, "type": "tool_call"}],
                ),
                AIMessage(content="推荐先去东京，再去大阪。"),
            ],
            tools=[get_current_time],
        )

    service, user = await _make_service(monkeypatch, tmp_path, factory)

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-1", user_message="帮我规划日本行程", locale="zh-CN"),
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == [
        "turn.start",
        "part.delta",   # 第一段文本（工具调用前的模型消息）+ seal
        "part.delta",   # seal（工具来临前收尾）
        "tool.start",
        "tool.done",
        "part.delta",   # 第二段文本
        "message.completed",
        "turn.done",
    ]
    assert events[0][1]["user_message"]["text"] == "帮我规划日本行程"
    assert events[0][1]["assistant_message"]["status"] == "streaming"
    assert events[1][1]["text_delta"] == "我先查一下当前时间，再帮你排顺序。"
    assert events[3][1]["part"]["tool_name"] == "get_current_time"
    assert events[4][1]["part"]["status"] == "success"
    assert events[5][1]["text_delta"] == "推荐先去东京，再去大阪。"
    assert events[-2][1]["message"]["text"] == "我先查一下当前时间，再帮你排顺序。推荐先去东京，再去大阪。"
    assert events[-2][1]["message"]["status"] == "completed"

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
    assert detail.messages[1].meta.tool_traces[1].phase == "returned"
    assert detail.messages[1].meta.tool_traces[1].payload == "当前时间为21:02:21"


@pytest.mark.asyncio
async def test_travel_agent_service_stream_invoke_without_token_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service, user = await _make_service(
        monkeypatch, tmp_path, lambda: _agent([AIMessage(content="只返回最终答案")])
    )

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-2", user_message="直接给结果", locale="zh-CN"),
    ):
        events.append((event_name, payload))

    names = [name for name, _ in events]
    assert names == ["turn.start", "part.delta", "message.completed", "turn.done"]
    assert events[1][1]["text_delta"] == "只返回最终答案"
    assert events[2][1]["message"]["text"] == "只返回最终答案"
    assert events[2][1]["message"]["parts"][0]["type"] == "text"


@pytest.mark.asyncio
async def test_travel_agent_service_persists_reasoning_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def factory():
        return _agent(
            [
                AIMessage(
                    content=[
                        {"type": "reasoning", "reasoning": "先分析需求。"},
                        {"type": "text", "text": "给你一个推荐方案。"},
                    ]
                )
            ]
        )

    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    service, user = await _make_service(monkeypatch, tmp_path, factory)

    events: list[tuple[str, dict]] = []
    async for event_name, payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-reasoning", user_message="帮我想一下方案", locale="zh-CN"),
    ):
        events.append((event_name, payload))

    assert events[0][0] == "turn.start"
    deltas = [(p.get("part_type"), p.get("text_delta")) for n, p in events if n == "part.delta" and p.get("text_delta")]
    assert ("reasoning", "先分析需求。") in deltas
    assert ("text", "给你一个推荐方案。") in deltas

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
    capture: list[dict] = []
    service, user = await _make_service(
        monkeypatch, tmp_path, lambda: _agent([AIMessage(content="收到")], capture=capture)
    )

    async for _event_name, _payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-3", user_message="第一句", locale="zh-CN"),
    ):
        pass

    async for _event_name, _payload in service.stream_invoke(
        user.id,
        ChatInvokeRequest(thread_id="thread-3", user_message="第二句", locale="zh-CN"),
    ):
        pass

    assert len(capture) == 2
    human_messages = [m for m in capture[0]["messages"] if isinstance(m, HumanMessage)]
    assert human_messages[-1].content == "第一句"
    human_messages = [m for m in capture[1]["messages"] if isinstance(m, HumanMessage)]
    assert human_messages[-1].content == "第二句"
    assert capture[0]["context"].user_id == user.id
    assert capture[0]["context"].thread_id == "thread-3"
    assert capture[0]["context"].locale == "zh-CN"
    assert capture[0]["context"].model_profile_key == "standard"
    assert capture[0]["context"].session_meta == {}
    assert capture[1]["context"].user_id == user.id


@pytest.mark.asyncio
async def test_travel_agent_service_startup_uses_context_schema_and_middleware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def _fake_create_agent(**kwargs):
        captured.update(kwargs)
        return _agent([AIMessage(content="ok")])

    async def _fake_load_mcp_tools(_connections):
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(tools=[], connected_servers=["demo"], errors=[])

    monkeypatch.setattr("app.agent.runtime.load_mcp_connections", lambda _path: {})
    monkeypatch.setattr("app.agent.runtime.load_mcp_tools", _fake_load_mcp_tools)
    # SummarizationMiddleware 需要真实模型实例，这里给轻量 fake
    from langchain_core.language_models import FakeMessagesListChatModel

    fake_chat_model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    monkeypatch.setattr(
        "app.agent.runtime.build_chat_models_by_profile",
        lambda: {"standard": fake_chat_model, "thinking": fake_chat_model},
    )
    dummy_checkpointer = _DummyCheckpointer()

    async def _fake_build_memory_runtime(_path: Path):
        return dummy_checkpointer, None

    monkeypatch.setattr("app.agent.runtime.build_memory_runtime", _fake_build_memory_runtime)
    monkeypatch.setattr("app.agent.runtime.create_agent", _fake_create_agent)

    # provider 现在禁止默认模型兜底，测试必须显式提供模型环境变量
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "fake-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text("{}", encoding="utf-8")

    sqlite_db = tmp_path / "chat.db"
    bootstrap_sqlite_database(sqlite_db)
    service = TravelAgentService(mcp_config_path=cfg, sqlite_db_path=sqlite_db)
    await service.startup()

    assert captured["context_schema"].__name__ == "AgentRequestContext"
    middleware = captured["middleware"]
    assert isinstance(middleware, list)
    # 三个固定 middleware（dynamic_prompt + Summarization + ToolError）
    # 加上动态注入的 ModelSelectionMiddleware
    assert len(middleware) == 4
    middleware_names = [type(m).__name__ for m in middleware]
    assert "ModelSelectionMiddleware" in middleware_names
    assert "SummarizationMiddleware" in middleware_names
    assert "ToolErrorMiddleware" in middleware_names
