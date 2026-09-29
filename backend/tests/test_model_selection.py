"""模型切换（ModelSelectionMiddleware）行为验证。

覆盖三层：
1. 单元层：wrap_model_call / awrap_model_call 按档位 override、未知档位回退默认。
2. 组合层：真实 create_agent + 完整 middleware 列表下，不同 context 档位
   路由到不同模型实例；SummarizationMiddleware（before_model）不干扰选择。
3. 顺序层：ModelSelectionMiddleware 位于列表末尾（最内层），override 必然生效。
"""

from __future__ import annotations

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.context import AgentRequestContext
from app.agent.middleware import ModelSelectionMiddleware, build_agent_middleware


class _RecordingFakeModel(FakeMessagesListChatModel):
    """带名字与调用计数的假模型，用于验证路由到了哪个实例。"""

    calls: int = 0

    def __init__(self, name: str) -> None:
        super().__init__(responses=[AIMessage(content=f"reply-from-{name}")])
        self.name = name

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _acall(self, messages, stop=None, **kwargs):
        self.calls += 1
        return await super()._acall(messages, stop=stop, **kwargs)


def _make_request(model, profile_key: str):
    """构造最小 ModelRequest，模拟 model 节点发起的一次调用。"""
    from langchain.agents.middleware import ModelRequest
    from langchain.agents.middleware.types import AgentState
    from langchain_core.messages import SystemMessage
    from langgraph.runtime import Runtime

    state = AgentState(values={"messages": []})
    runtime = Runtime(context=AgentRequestContext(user_id="u1", thread_id="t1", model_profile_key=profile_key))
    return ModelRequest(
        model=model,
        messages=[HumanMessage(content="hi")],
        system_message=SystemMessage(content="sys"),
        tools=[],
        response_format=None,
        state=state,
        runtime=runtime,
    )


def test_wrap_model_call_overrides_model_by_profile() -> None:
    standard_model = _RecordingFakeModel("standard")
    thinking_model = _RecordingFakeModel("thinking")
    middleware = ModelSelectionMiddleware(
        chat_models_by_profile={"standard": standard_model, "thinking": thinking_model},
        default_profile_key="standard",
    )

    captured: dict[str, object] = {}

    def handler(request):
        captured["model"] = request.model
        return AIMessage(content="ok")

    middleware.wrap_model_call(_make_request(standard_model, "standard"), handler)
    assert captured["model"] is standard_model

    middleware.wrap_model_call(_make_request(standard_model, "thinking"), handler)
    assert captured["model"] is thinking_model


@pytest.mark.asyncio
async def test_awrap_model_call_overrides_model_by_profile() -> None:
    standard_model = _RecordingFakeModel("standard")
    thinking_model = _RecordingFakeModel("thinking")
    middleware = ModelSelectionMiddleware(
        chat_models_by_profile={"standard": standard_model, "thinking": thinking_model},
        default_profile_key="standard",
    )

    captured: dict[str, object] = {}

    async def handler(request):
        captured["model"] = request.model
        return AIMessage(content="ok")

    await middleware.awrap_model_call(_make_request(standard_model, "thinking"), handler)
    assert captured["model"] is thinking_model


def test_unknown_profile_falls_back_to_default() -> None:
    standard_model = _RecordingFakeModel("standard")
    middleware = ModelSelectionMiddleware(
        chat_models_by_profile={"standard": standard_model, "thinking": _RecordingFakeModel("thinking")},
        default_profile_key="standard",
    )

    captured: dict[str, object] = {}

    def handler(request):
        captured["model"] = request.model
        return AIMessage(content="ok")

    middleware.wrap_model_call(_make_request(standard_model, "nonexistent"), handler)
    assert captured["model"] is standard_model


def _agent_context(profile_key: str) -> AgentRequestContext:
    return AgentRequestContext(
        user_id="u1",
        thread_id="t-switch",
        model_profile_key=profile_key,
        session_meta={},
    )


@pytest.mark.asyncio
async def test_full_agent_routes_profile_to_distinct_models() -> None:
    """真实 create_agent + 完整 middleware 列表下，档位切换路由到不同模型实例。"""
    standard_model = _RecordingFakeModel("standard")
    thinking_model = _RecordingFakeModel("thinking")
    middleware = build_agent_middleware(
        chat_models_by_profile={"standard": standard_model, "thinking": thinking_model},
        default_profile_key="standard",
    )
    agent = create_agent(
        model=standard_model,
        tools=[],
        context_schema=AgentRequestContext,
        middleware=middleware,
    )

    for profile_key, expected in (
        ("standard", standard_model),
        ("thinking", thinking_model),
        ("standard", standard_model),
    ):
        stream = await agent.astream_events(
            {"messages": [HumanMessage(content=f"hello {profile_key}")]},
            context=_agent_context(profile_key),
            version="v3",
        )
        async for _event in stream:
            pass
        assert expected.calls >= 1, f"profile={profile_key} should invoke its own model"
    # 交叉验证：thinking 档位的调用没有落在 standard 实例之外
    assert thinking_model.calls == 1
    assert standard_model.calls == 2


def test_model_selection_is_innermost_in_default_stack() -> None:
    """ModelSelection 必须是列表最后一项（最内层），保证 override 不被后续层覆盖。"""
    middleware = build_agent_middleware(
        chat_models_by_profile={"standard": _RecordingFakeModel("s"), "thinking": _RecordingFakeModel("t")},
        default_profile_key="standard",
    )
    assert type(middleware[-1]) is ModelSelectionMiddleware
