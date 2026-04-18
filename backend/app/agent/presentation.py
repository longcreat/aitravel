"""Agent 最终消息展示与持久化表示构建。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage

from app.agent.runtime import AgentRuntime
from app.schemas.chat import (
    ChatInvokeResponse,
    ChatMetaInfo,
    RenderStepSegment,
    RenderTextSegment,
    StepDetailItem,
    StepGroup,
    ToolTrace,
)


def build_final_response(
    *,
    latest_values: dict[str, Any] | None,
    accumulated_chunk: AIMessageChunk | None,
    streamed_tool_traces: list[ToolTrace],
    runtime: AgentRuntime,
) -> ChatInvokeResponse:
    """根据流式过程构建最终响应对象。"""
    values = latest_values if isinstance(latest_values, dict) else {}
    messages = _extract_state_messages(values.get("messages"))

    assistant_from_chunk = _content_to_text(accumulated_chunk.content).strip() if accumulated_chunk else ""
    reasoning_from_chunk = _message_reasoning_text(accumulated_chunk).strip() if accumulated_chunk else ""
    assistant_from_state, step_groups, render_segments = _build_step_presentation(messages)
    reasoning_from_state = _messages_reasoning_text(messages)
    assistant_message = assistant_from_chunk or assistant_from_state
    reasoning_text = reasoning_from_chunk or reasoning_from_state

    traces_from_state = _extract_tool_traces(messages)
    final_tool_traces = traces_from_state or streamed_tool_traces

    return ChatInvokeResponse(
        assistant_message=assistant_message,
        meta=ChatMetaInfo(
            tool_traces=final_tool_traces,
            step_groups=step_groups,
            render_segments=render_segments,
            reasoning_text=reasoning_text or None,
            reasoning_state="completed" if reasoning_text else None,
            mcp_connected_servers=runtime.mcp_bundle.connected_servers,
            mcp_errors=runtime.mcp_bundle.errors,
        ),
    )


def _extract_state_messages(payload: Any) -> list[BaseMessage]:
    """从 LangGraph values 中抽取消息列表。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, BaseMessage)]
    return list(_iter_base_messages(payload))


def _iter_base_messages(payload: Any):
    """递归遍历负载中的 LangChain `BaseMessage`。"""
    if isinstance(payload, BaseMessage):
        yield payload
        return

    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, (dict, list, tuple, set, BaseMessage)):
                yield from _iter_base_messages(value)
        return

    if isinstance(payload, (list, tuple, set)):
        for item in payload:
            if isinstance(item, (dict, list, tuple, set, BaseMessage)):
                yield from _iter_base_messages(item)


def _append_render_text_segment(render_segments: list[RenderTextSegment | RenderStepSegment], text: str) -> None:
    """把文本追加到渲染片段列表中，并自动合并相邻文本段。"""
    if not text:
        return

    last_segment = render_segments[-1] if render_segments else None
    if isinstance(last_segment, RenderTextSegment):
        last_segment.text += text
        return

    render_segments.append(RenderTextSegment(text=text))


def _get_or_create_step_group(
    step_groups: list[StepGroup],
    render_segments: list[RenderTextSegment | RenderStepSegment],
) -> StepGroup:
    """返回当前连续工具调用区间的 step group。"""
    last_segment = render_segments[-1] if render_segments else None
    if isinstance(last_segment, RenderStepSegment):
        existing = next((group for group in step_groups if group.id == last_segment.step_group_id), None)
        if existing is not None:
            return existing

    group = StepGroup(id=f"step-{len(step_groups) + 1}")
    step_groups.append(group)
    render_segments.append(RenderStepSegment(step_group_id=group.id))
    return group


def _find_step_item(step_groups: list[StepGroup], tool_call_id: str) -> StepDetailItem | None:
    """按 tool_call_id 查找已存在的步骤项。"""
    for group in reversed(step_groups):
        for item in group.items:
            if item.id == tool_call_id:
                return item
    return None


def _format_tool_name(tool_name: str) -> str:
    """把工具名做轻量可读化。"""
    return tool_name.replace("_", " ").replace("-", " ").strip()


def _summarize_step_payload(payload: Any, status: str) -> str:
    """生成步骤详情里的简短说明。"""
    if status == "running":
        return "Running"

    text = _content_to_text(payload).strip()
    if text and len(text) <= 80 and not text.startswith(("{", "[")):
        return text

    return "Returned an error" if status == "error" else "Completed"


def _visible_reply_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """截取最近一轮用户消息之后的 assistant/tool 消息。"""
    start_index = 0
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            start_index = index + 1
    return messages[start_index:]


def _build_step_presentation(
    messages: list[BaseMessage],
) -> tuple[str, list[StepGroup], list[RenderTextSegment | RenderStepSegment]]:
    """从最终消息列表恢复前端可渲染的文本段与 step 段时间线。"""
    relevant_messages = _visible_reply_messages(messages)
    step_groups: list[StepGroup] = []
    render_segments: list[RenderTextSegment | RenderStepSegment] = []

    for message in relevant_messages:
        if isinstance(message, AIMessage):
            text = _content_to_text(message.content).strip()
            if text:
                _append_render_text_segment(render_segments, text)

            if not message.tool_calls:
                continue

            step_group = _get_or_create_step_group(step_groups, render_segments)
            for call in message.tool_calls:
                if not isinstance(call, dict):
                    continue
                tool_call_id = str(call.get("id") or f"{call.get('name', 'tool')}-{len(step_group.items) + 1}")
                if any(item.id == tool_call_id for item in step_group.items):
                    continue
                step_group.items.append(
                    StepDetailItem(
                        id=tool_call_id,
                        tool_name=_format_tool_name(str(call.get("name", "unknown"))),
                        status="running",
                        summary=_summarize_step_payload(call.get("args", {}), "running"),
                    )
                )
            continue

        if not isinstance(message, ToolMessage):
            continue

        result_status = "error" if str(getattr(message, "status", "")).lower() == "error" else "success"
        tool_call_id = str(message.tool_call_id or f"{message.name or 'tool'}-{len(step_groups) + 1}")
        existing_item = _find_step_item(step_groups, tool_call_id)
        if existing_item is not None:
            existing_item.status = result_status  # type: ignore[assignment]
            existing_item.summary = _summarize_step_payload(message.content, result_status)
            continue

        step_group = _get_or_create_step_group(step_groups, render_segments)
        step_group.items.append(
            StepDetailItem(
                id=tool_call_id,
                tool_name=_format_tool_name(str(message.name or "unknown")),
                status=result_status,  # type: ignore[arg-type]
                summary=_summarize_step_payload(message.content, result_status),
            )
        )

    assistant_text = "".join(
        segment.text for segment in render_segments if isinstance(segment, RenderTextSegment)
    ).strip()
    return assistant_text, step_groups, render_segments


def _extract_tool_traces(messages: list[BaseMessage]) -> list[ToolTrace]:
    """从消息列表中重建工具调用轨迹。"""
    traces: list[ToolTrace] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if isinstance(call, dict):
                    traces.append(
                        ToolTrace(
                            phase="called",
                            tool_name=str(call.get("name", "unknown")),
                            payload=call.get("args", {}),
                            tool_call_id=str(call.get("id")) if call.get("id") else None,
                            result_status=None,
                        )
                    )
            continue

        if isinstance(message, ToolMessage):
            traces.append(
                ToolTrace(
                    phase="returned",
                    tool_name=str(message.name or "unknown"),
                    payload=_content_to_text(message.content),
                    tool_call_id=str(message.tool_call_id) if message.tool_call_id else None,
                    result_status="error" if str(getattr(message, "status", "")).lower() == "error" else "success",
                )
            )

    return traces


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


def _message_reasoning_text(message: AIMessage | AIMessageChunk | None) -> str:
    """从单条 AI 消息中提取 reasoning 文本。"""
    if message is None:
        return ""

    reasoning_content = getattr(message, "additional_kwargs", {}).get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content.strip()

    return _reasoning_blocks_to_text(getattr(message, "content", None))


def _messages_reasoning_text(messages: list[BaseMessage]) -> str:
    """从最近一轮回复消息中恢复完整 reasoning 文本。"""
    chunks: list[str] = []
    for message in _visible_reply_messages(messages):
        if not isinstance(message, AIMessage):
            continue
        reasoning_text = _message_reasoning_text(message)
        if reasoning_text:
            chunks.append(reasoning_text)
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
