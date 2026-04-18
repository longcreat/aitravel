"""Agent 运行时上下文定义。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRequestContext(BaseModel):
    """单轮 Agent 运行期间的上下文。

    这层上下文通过 `context_schema` 注入到 LangChain runtime，供 middleware、
    工具和后续 store/interceptor 使用。
    """

    user_id: str
    thread_id: str
    locale: str = "zh-CN"
    model_profile_key: str = "standard"
    session_meta: dict[str, Any] = Field(default_factory=dict)
