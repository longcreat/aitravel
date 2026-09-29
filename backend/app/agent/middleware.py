"""Agent middleware 定义。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    SummarizationMiddleware,
    ToolErrorMiddleware,
    dynamic_prompt,
)
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models import BaseChatModel

from app.agent.context import AgentRequestContext
from app.prompt.system import TRAVEL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "Asia/Shanghai"
_WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 长会话保护：接近该 token 量时把旧消息折叠成摘要，防止上下文窗口溢出
_SUMMARIZATION_TRIGGER_TOKENS = 4000
_SUMMARIZATION_KEEP_MESSAGES = 20


def _resolve_timezone(timezone_name: str) -> tuple[str, Any]:
    """解析时区，回退到固定偏移；返回 (canonical_name, tzinfo)。"""
    try:
        return timezone_name, ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        fallback = {
            "Asia/Shanghai": dt_timezone(timedelta(hours=8), name="Asia/Shanghai"),
            "UTC": dt_timezone.utc,
        }.get(timezone_name)
        if fallback is not None:
            return timezone_name, fallback
        # 未知时区，回退到默认
        return _DEFAULT_TIMEZONE, dt_timezone(timedelta(hours=8), name=_DEFAULT_TIMEZONE)


def _format_runtime_clock(timezone_name: str, *, now: datetime | None = None) -> str:
    """返回提示词里展示的 "当前时间" 行。"""
    canonical, tzinfo = _resolve_timezone(timezone_name)
    current = now.astimezone(tzinfo) if now is not None else datetime.now(tzinfo)
    weekday = _WEEKDAY_ZH[current.weekday()]
    return (
        f"- 当前时间：{current.strftime('%Y-%m-%d %H:%M')} {weekday} "
        f"（{canonical}，UTC{current.strftime('%z')}）"
    )


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

    # 时间感知：每次请求都注入"当前时间"，避免模型用预训练数据猜测当下日期。
    timezone_name = _DEFAULT_TIMEZONE
    if context.session_meta:
        ctx_tz = context.session_meta.get("timezone")
        if isinstance(ctx_tz, str) and ctx_tz.strip():
            timezone_name = ctx_tz.strip()
    context_lines.append(_format_runtime_clock(timezone_name))

    if context.locale and context.locale != "zh-CN":
        context_lines.append(f"- 优先使用语言环境：{context.locale}")
    if context.session_meta:
        context_lines.append(f"- 会话元信息：{_serialize_session_meta(context.session_meta)}")

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
        # 未拿到 runtime context 也至少注入当前时间
        return "\n".join(
            [
                TRAVEL_SYSTEM_PROMPT,
                "",
                "运行时上下文：",
                _format_runtime_clock(_DEFAULT_TIMEZONE),
            ]
        )
    return build_runtime_system_prompt(runtime_context)


def _tool_error_to_message(exc: Exception, request: ToolCallRequest) -> str:
    """统一把工具异常转换成 status=error 的 ToolMessage 文本。

    内建 ``ToolErrorMiddleware`` 自身会透传 ``GraphBubbleUp``（interrupt 机制），
    其余异常经此全部转成错误 ToolMessage 交回模型，行为与旧手写边界一致。
    """
    tool_name = str(request.tool_call.get("name") or "unknown")
    return f"工具 {tool_name} 执行失败：{exc}"


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

    - ``travel_dynamic_prompt``：运行时上下文注入系统提示词
    - ``SummarizationMiddleware``：长会话自动摘要，防上下文溢出
    - ``ToolErrorMiddleware``：工具异常统一转错误 ToolMessage（内建，透传 interrupt）
    - ``ModelSelectionMiddleware``：按档位切换模型实例，必须挂在最内层（最后）
    """
    middleware: list[Any] = [travel_dynamic_prompt]
    default_model = chat_models_by_profile.get(default_profile_key) if chat_models_by_profile and default_profile_key else None
    if isinstance(default_model, BaseChatModel):
        # 仅在拿到真实模型实例时挂载；测试桩传入字符串模型名时跳过
        middleware.append(
            SummarizationMiddleware(
                model=default_model,
                trigger=("tokens", _SUMMARIZATION_TRIGGER_TOKENS),
                keep=("messages", _SUMMARIZATION_KEEP_MESSAGES),
            )
        )
    if chat_models_by_profile and default_profile_key:
        middleware.append(ToolErrorMiddleware(on_error=_tool_error_to_message))
    if chat_models_by_profile and default_profile_key:
        middleware.append(
            ModelSelectionMiddleware(
                chat_models_by_profile=chat_models_by_profile,
                default_profile_key=default_profile_key,
            )
        )
    return middleware
