"""聊天领域模型定义。

本模块统一维护后端聊天接口与流式事件的数据结构，供 API 层、
服务层与测试共同复用，避免字段漂移。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ChatModelProfileKind = Literal["standard", "thinking"]


class ChatInvokeRequest(BaseModel):
    """聊天请求参数。

    thread_id 用于会话记忆隔离；session_meta 预留给业务侧扩展透传。
    """

    thread_id: str = Field(default_factory=lambda: str(uuid4()))
    user_message: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN")
    model_profile_key: str | None = None
    session_meta: dict[str, Any] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    """工具调用轨迹条目。"""

    phase: Literal["called", "returned"]
    tool_name: str
    payload: Any = None
    tool_call_id: str | None = None
    result_status: Literal["success", "error"] | None = None


class StepDetailItem(BaseModel):
    """单条工具步骤详情。"""

    id: str
    tool_name: str
    status: Literal["running", "success", "error"]
    summary: str


class StepGroup(BaseModel):
    """连续工具调用区间的聚合结果。"""

    id: str
    items: list[StepDetailItem] = Field(default_factory=list)


class RenderTextSegment(BaseModel):
    """正文文本片段。"""

    type: Literal["text"] = "text"
    text: str


class RenderStepSegment(BaseModel):
    """step 入口片段。"""

    type: Literal["step"] = "step"
    step_group_id: str


ChatRenderSegment = RenderTextSegment | RenderStepSegment


class ChatMetaInfo(BaseModel):
    """聊天附加元信息集合。"""

    tool_traces: list[ToolTrace] = Field(default_factory=list)
    step_groups: list[StepGroup] = Field(default_factory=list)
    render_segments: list[ChatRenderSegment] = Field(default_factory=list)
    reasoning_text: str | None = None
    reasoning_state: Literal["streaming", "completed"] | None = None
    mcp_connected_servers: list[str] = Field(default_factory=list)
    mcp_errors: list[str] = Field(default_factory=list)


class AssistantVersion(BaseModel):
    """助手回复的单个持久化版本。"""

    id: int
    version_index: Literal[1, 2, 3]
    kind: Literal["original", "regenerated"]
    text: str
    meta: ChatMetaInfo | None = None
    feedback: Literal["up", "down"] | None = None
    created_at: str


class ChatInvokeResponse(BaseModel):
    """最终聊天结果（供服务层内部组装与持久化）。"""

    assistant_message: str
    meta: ChatMetaInfo = Field(default_factory=ChatMetaInfo)


class StreamErrorPayload(BaseModel):
    """流式错误事件负载。"""

    message: str


class PersistedChatMessage(BaseModel):
    """持久化后的聊天消息。"""

    id: int
    role: Literal["user", "assistant"]
    text: str
    meta: ChatMetaInfo | None = None
    reply_to_message_id: int | None = None
    current_version_id: int | None = None
    versions: list[AssistantVersion] = Field(default_factory=list)
    can_regenerate: bool = False
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
    model_profile_key: str
    messages: list[PersistedChatMessage] = Field(default_factory=list)


class ChatModelProfile(BaseModel):
    """前端可见的聊天模型档位。"""

    key: str
    label: str
    kind: ChatModelProfileKind
    is_default: bool = False


class ListChatModelProfilesResponse(BaseModel):
    """聊天模型档位列表。"""

    default_profile_key: str
    profiles: list[ChatModelProfile] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(min_length=1, max_length=100)


class UpdateSessionModelProfileRequest(BaseModel):
    """更新线程当前模型档位。"""

    model_profile_key: str = Field(min_length=1, max_length=64)


class SessionModelProfileState(BaseModel):
    """线程当前模型档位状态。"""

    thread_id: str
    model_profile_key: str


class SwitchAssistantVersionRequest(BaseModel):
    """切换 assistant 当前展示版本。"""

    version_id: int = Field(gt=0)


class UpdateAssistantFeedbackRequest(BaseModel):
    """更新 assistant version 点赞/点踩状态。"""

    feedback: Literal["up", "down"] | None = None
