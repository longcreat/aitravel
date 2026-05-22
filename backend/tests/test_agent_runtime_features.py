from __future__ import annotations

import re
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langgraph.runtime import Runtime

from app.agent.context import AgentRequestContext
from app.agent.middleware import (
    _format_runtime_clock,
    build_runtime_system_prompt,
    travel_dynamic_prompt,
)
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
    assert "当前时间：" in prompt
    # 时区使用 session_meta 里的 UTC
    assert "（UTC，UTC+0000）" in prompt
    # 形如 "2026-05-22 13:00 星期五"
    assert re.search(r"当前时间：\d{4}-\d{2}-\d{2} \d{2}:\d{2} 星期[一二三四五六日]", prompt)


def test_build_runtime_system_prompt_defaults_to_shanghai_when_no_timezone():
    prompt = build_runtime_system_prompt(
        AgentRequestContext(user_id="u1", thread_id="t1", locale="zh-CN")
    )

    assert "当前时间：" in prompt
    assert "Asia/Shanghai" in prompt


def test_format_runtime_clock_falls_back_for_unknown_timezone():
    line = _format_runtime_clock("Mars/Phobos")

    # 未知时区回退到上海
    assert "Asia/Shanghai" in line
    assert "当前时间：" in line


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
