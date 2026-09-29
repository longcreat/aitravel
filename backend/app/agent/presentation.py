"""Agent 最终消息展示与持久化表示构建。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

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
) -> ChatInvokeResponse:
    """根据流式累计结果构建最终响应对象。"""
    assistant_from_chunk = assistant_text.strip()
    reasoning_from_chunk = reasoning_text.strip()

    return ChatInvokeResponse(
        assistant_message=assistant_from_chunk,
        meta=ChatMetaInfo(
            tool_traces=streamed_tool_traces,
            reasoning_text=reasoning_from_chunk or None,
            reasoning_state="completed" if reasoning_from_chunk else None,
            mcp_connected_servers=runtime.mcp_bundle.connected_servers,
            mcp_errors=runtime.mcp_bundle.errors,
        ),
    )


def _reasoning_blocks_to_text(content: Any) -> str:
    """从 content block 列表中提取 reasoning 文本。"""
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "").strip().lower()
        if item_type not in {"reasoning", "reasoning_content"}:
            continue

        reasoning = item.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            chunks.append(reasoning)

        summary = item.get("summary")
        if isinstance(summary, list):
            for summary_item in summary:
                if not isinstance(summary_item, dict):
                    continue
                if str(summary_item.get("type") or "").strip().lower() != "summary_text":
                    continue
                text = summary_item.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)

        reasoning_content = item.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            chunks.append(reasoning_content)

        text = item.get("text")
        if item_type == "reasoning_content" and isinstance(text, str) and text:
            chunks.append(text)

    return "".join(chunks).strip()


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
