"""Agent middleware 定义。"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    dynamic_prompt,
    wrap_tool_call,
)
from langchain.agents.middleware.types import ModelRequest as ModelRequestT
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from app.agent.context import AgentRequestContext
from app.prompt.system import TRAVEL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


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
def travel_dynamic_prompt(request: ModelRequestT[AgentRequestContext]) -> str:
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


class ModelSelectionMiddleware(AgentMiddleware):
    """根据运行时档位选择对应 ChatModel 实例。

    依据 LangChain v1 官方推荐的 ``request.override(model=...)`` 模式实现。每次
    模型调用都会从 ``request.runtime.context.model_profile_key`` 取出当前档位，
    把请求里默认绑定的 model 替换成对应的实例。

    这能正确绕过 ``bind_tools`` 等 wrapping 的副作用——旧实现里通过
    ``configurable_fields`` 注入的 model_name / extra_body 会在 ``bind_tools``
    之后失效；middleware 在请求链最末一步执行，因此 ``override`` 的 model 一定生效。
    """

    def __init__(
        self,
        chat_models_by_profile: dict[str, BaseChatModel],
        default_profile_key: str,
    ) -> None:
        super().__init__()
        if not chat_models_by_profile:
            raise ValueError("chat_models_by_profile must contain at least one entry")
        if default_profile_key not in chat_models_by_profile:
            raise ValueError(
                f"default_profile_key={default_profile_key!r} not in registered models "
                f"{list(chat_models_by_profile.keys())}"
            )
        self._models = chat_models_by_profile
        self._default_key = default_profile_key

    def _select_model(self, profile_key: str | None) -> BaseChatModel:
        if profile_key and profile_key in self._models:
            return self._models[profile_key]
        if profile_key:
            logger.warning(
                "Unknown model_profile_key=%s, falling back to default=%s",
                profile_key,
                self._default_key,
            )
        return self._models[self._default_key]

    def _resolve_profile_key(self, request: ModelRequest[Any]) -> str | None:
        runtime_context = request.runtime.context if request.runtime is not None else None
        return getattr(runtime_context, "model_profile_key", None)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse],
    ) -> ModelResponse:
        chosen_model = self._select_model(self._resolve_profile_key(request))
        return handler(request.override(model=chosen_model))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> ModelResponse:
        chosen_model = self._select_model(self._resolve_profile_key(request))
        return await handler(request.override(model=chosen_model))


def build_agent_middleware(
    chat_models_by_profile: dict[str, BaseChatModel] | None = None,
    default_profile_key: str | None = None,
) -> list[Any]:
    """返回当前 agent 需要挂载的官方 middleware 列表。

    若提供了模型档位字典，则会在末尾追加一个 ``ModelSelectionMiddleware``，
    让运行时根据 ``AgentRequestContext.model_profile_key`` 切换模型实例。
    """
    middleware: list[Any] = [travel_dynamic_prompt, tool_error_boundary]
    if chat_models_by_profile and default_profile_key:
        middleware.append(
            ModelSelectionMiddleware(
                chat_models_by_profile=chat_models_by_profile,
                default_profile_key=default_profile_key,
            )
        )
    return middleware
