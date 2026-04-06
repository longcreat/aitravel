"""聊天领域模型定义。

本模块统一维护后端聊天接口与流式事件的数据结构，供 API 层、
服务层与测试共同复用，避免字段漂移。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ItineraryItem(BaseModel):
    """结构化行程中的单日条目。"""

    day: int = Field(..., ge=1)
    city: str
    activities: list[str] = Field(default_factory=list)
    notes: str | None = None


class StructuredTravelPlan(BaseModel):
    """模型结构化输出的旅行计划。"""

    summary: str = Field(description="A concise travel recommendation summary")
    itinerary: list[ItineraryItem] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)


class ChatInvokeRequest(BaseModel):
    """聊天请求参数。

    thread_id 用于会话记忆隔离；session_meta 预留给业务侧扩展透传。
    """

    thread_id: str = Field(default_factory=lambda: str(uuid4()))
    user_message: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN")
    session_meta: dict[str, Any] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    """工具调用轨迹条目。"""

    phase: Literal["called", "returned"]
    tool_name: str
    payload: Any = None


class ChatDebugInfo(BaseModel):
    """聊天调试信息集合。"""

    tool_traces: list[ToolTrace] = Field(default_factory=list)
    mcp_connected_servers: list[str] = Field(default_factory=list)
    mcp_errors: list[str] = Field(default_factory=list)


class ChatInvokeResponse(BaseModel):
    """最终聊天结果（用于流式 final 事件负载）。"""

    assistant_message: str
    itinerary: list[ItineraryItem] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    debug: ChatDebugInfo = Field(default_factory=ChatDebugInfo)


class StreamStartPayload(BaseModel):
    """流式开始事件负载。"""

    thread_id: str
    started_at: str


class StreamTokenPayload(BaseModel):
    """流式 token 事件负载（LangChain 原生 chunk）。"""

    chunk: "StreamChunkPayload"
    meta: "StreamChunkMetaPayload"


class StreamChunkPayload(BaseModel):
    """LangChain `AIMessageChunk` 的可序列化字段快照。"""

    id: str | None = None
    type: str | None = None
    content: Any = None
    name: str | None = None
    chunk_position: Any = None
    tool_call_chunks: list[Any] = Field(default_factory=list)
    tool_calls: list[Any] = Field(default_factory=list)
    invalid_tool_calls: list[Any] = Field(default_factory=list)
    usage_metadata: Any = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)


class StreamChunkMetaPayload(BaseModel):
    """流式 chunk 的元信息。"""

    node: str | None = None
    sequence: int = Field(ge=1)
    emitted_at: str


class StreamToolPayload(BaseModel):
    """流式工具事件负载。"""

    tool_name: str
    payload: Any = None


class StreamErrorPayload(BaseModel):
    """流式错误事件负载。"""

    message: str


class PersistedChatMessage(BaseModel):
    """持久化后的聊天消息。"""

    id: int
    role: Literal["user", "assistant"]
    text: str
    itinerary: list[ItineraryItem] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    debug: ChatDebugInfo | None = None
    created_at: str


class SessionSummary(BaseModel):
    """会话摘要信息。"""

    thread_id: str
    title: str
    created_at: str
    updated_at: str
    last_message_preview: str


class SessionDetail(BaseModel):
    """会话详情信息（含历史消息）。"""

    thread_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[PersistedChatMessage] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(min_length=1, max_length=100)
