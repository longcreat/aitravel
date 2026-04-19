"""Agent middleware 定义。"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import dynamic_prompt, wrap_tool_call
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from app.agent.context import AgentRequestContext
from app.prompt.system import TRAVEL_SYSTEM_PROMPT


def _serialize_session_meta(session_meta: dict[str, Any]) -> str:
    """把 session_meta 稳定序列化成 prompt 可读文本。"""
    try:
        return json.dumps(session_meta, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(session_meta)


def build_runtime_system_prompt(context: AgentRequestContext) -> str:
    """基于运行时上下文生成最终系统提示词。"""
    prompt = TRAVEL_SYSTEM_PROMPT
    context_lines: list[str] = []

    if context.locale and context.locale != "zh-CN":
        context_lines.append(f"- 优先使用语言环境：{context.locale}")
    if context.session_meta:
        context_lines.append(f"- 会话元信息：{_serialize_session_meta(context.session_meta)}")

    if not context_lines:
        return prompt

    return "\n".join(
        [
            prompt,
            "",
            "运行时上下文：",
            *context_lines,
        ]
    )


@dynamic_prompt
def travel_dynamic_prompt(request: ModelRequest[AgentRequestContext]) -> str:
    """按运行时上下文动态拼装系统提示词。"""
    runtime_context = request.runtime.context if request.runtime is not None else None
    if runtime_context is None:
        return TRAVEL_SYSTEM_PROMPT
    return build_runtime_system_prompt(runtime_context)


@wrap_tool_call
async def tool_error_boundary(request, handler):
    """统一把工具异常转换成标准 ToolMessage。

    注意：GraphInterrupt（由 interrupt() 抛出）必须透传给 LangGraph，
    不能在此处被捕获——否则 human-in-the-loop 的 interrupt 机制将完全失效。
    """
    try:
        return await handler(request)
    except GraphInterrupt:
        raise  # 让 LangGraph 的 checkpoint / interrupt 机制正常接管
    except Exception as exc:  # pragma: no cover - exercised via agent runtime
        tool_name = request.tool.name if request.tool is not None else str(request.tool_call.get("name") or "unknown")
        tool_call_id = str(request.tool_call.get("id") or f"{tool_name}-error")
        return ToolMessage(
            content=f"工具 {tool_name} 执行失败：{exc}",
            name=tool_name,
            tool_call_id=tool_call_id,
            status="error",
        )


def build_agent_middleware() -> list[Any]:
    """返回当前 agent 需要挂载的官方 middleware 列表。"""
    return [travel_dynamic_prompt, tool_error_boundary]
