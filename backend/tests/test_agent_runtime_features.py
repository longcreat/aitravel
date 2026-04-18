from __future__ import annotations

from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langgraph.runtime import Runtime

from app.agent.context import AgentRequestContext
from app.agent.middleware import build_runtime_system_prompt, travel_dynamic_prompt
from app.tool.local_tools import get_current_time


def test_build_runtime_system_prompt_appends_runtime_context():
    prompt = build_runtime_system_prompt(
        AgentRequestContext(
            user_id="u1",
            thread_id="t1",
            locale="en-US",
            session_meta={"timezone": "UTC"},
        )
    )

    assert "运行时上下文：" in prompt
    assert "语言环境：en-US" in prompt
    assert "会话元信息" in prompt


def test_get_current_time_prefers_timezone_from_runtime_context():
    runtime = SimpleNamespace(
        context=AgentRequestContext(
            user_id="u1",
            thread_id="t1",
            locale="zh-CN",
            session_meta={"timezone": "UTC"},
        )
    )

    result = get_current_time.func(runtime=runtime)

    assert result["timezone"] == "UTC"


def test_dynamic_prompt_middleware_reads_context_from_model_request():
    captured: dict[str, str | None] = {}
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[],
        runtime=Runtime(
            context=AgentRequestContext(
                user_id="u1",
                thread_id="t1",
                locale="en-US",
                session_meta={"timezone": "UTC"},
            )
        ),
    )

    def _handler(next_request: ModelRequest[AgentRequestContext]):
        captured["system_prompt"] = next_request.system_prompt
        return "ok"

    result = travel_dynamic_prompt.wrap_model_call(request, _handler)

    assert result == "ok"
    assert captured["system_prompt"] is not None
    assert "运行时上下文：" in captured["system_prompt"]
    assert "语言环境：en-US" in captured["system_prompt"]
