"""LangSmith tracing 辅助封装。"""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any

from langsmith import tracing_context


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def is_langsmith_tracing_enabled() -> bool:
    """判断当前进程是否开启了 LangSmith tracing。"""
    return _env_flag("LANGSMITH_TRACING") or _env_flag("LANGCHAIN_TRACING_V2")


def langsmith_trace_context(
    operation: str,
    *,
    user_id: str,
    thread_id: str,
    locale: str | None = None,
    model_profile_key: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
):
    """构建当前请求的 LangSmith tracing 上下文。"""
    if not is_langsmith_tracing_enabled():
        return nullcontext()

    metadata: dict[str, Any] = {
        "operation": operation,
        "user_id": user_id,
        "thread_id": thread_id,
    }
    if locale:
        metadata["locale"] = locale
    if model_profile_key:
        metadata["model_profile_key"] = model_profile_key
    if extra_metadata:
        metadata.update(extra_metadata)

    project_name = os.getenv("LANGSMITH_PROJECT") or None
    tags = ["ai-travel-agent", operation]
    return tracing_context(
        project_name=project_name,
        tags=tags,
        metadata=metadata,
        enabled=True,
    )
