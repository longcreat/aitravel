"""Agent 最终消息展示与持久化表示构建。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from app.agent.runtime import AgentRuntime
from app.schemas.chat import (
    ChatInvokeResponse,
    ChatMetaInfo,
    ToolTrace,
)


def build_final_response(
    *,
    assistant_text: str,
    reasoning_text: str,
    streamed_tool_traces: list[ToolTrace],
    runtime: AgentRuntime,
    connector_servers: list[str] | None = None,
    connector_errors: list[str] | None = None,
) -> ChatInvokeResponse:
    """根据流式累计结果构建最终响应对象。

    connector_servers / connector_errors：用户级 connector 的加载结果，
    与全局 MCP 一并列进 meta（前端与排查都能看到"我的连接为什么没生效"）。
    """
    assistant_from_chunk = assistant_text.strip()
    reasoning_from_chunk = reasoning_text.strip()

    return ChatInvokeResponse(
        assistant_message=assistant_from_chunk,
        meta=ChatMetaInfo(
            tool_traces=streamed_tool_traces,
            reasoning_text=reasoning_from_chunk or None,
            reasoning_state="completed" if reasoning_from_chunk else None,
            mcp_connected_servers=[*runtime.mcp_bundle.connected_servers, *(connector_servers or [])],
            mcp_errors=[*runtime.mcp_bundle.errors, *(connector_errors or [])],
        ),
    )


def _content_to_text(content: Any) -> str:
    """将消息 content 统一归一化为字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            elif isinstance(item, dict) and str(item.get("type") or "").strip().lower() in {
                "reasoning",
                "reasoning_content",
            }:
                continue
            else:
                chunks.append(str(item))
        return "\n".join(chunks).strip()
    if content is None:
        return ""
    return str(content)


def _tool_message_payload(message: ToolMessage) -> Any:
    """返回工具轨迹里应保留的 payload。"""
    if message.artifact is not None:
        return message.artifact
    return _content_to_text(message.content)
