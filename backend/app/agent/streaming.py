"""Agent 流式执行与事件累计。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage, message_to_dict
from pydantic import BaseModel

from app.agent.context import AgentRequestContext
from app.agent.presentation import _content_to_text, _tool_message_payload
from app.agent.runtime import AgentRuntimeService
from app.llm.provider import get_llm_configurable
from app.schemas.chat import (
    ChatMessagePart,
    ChatReasoningPart,
    ChatTextPart,
    ChatToolPart,
    PartDeltaPayload,
    ToolPartPayload,
    ToolTrace,
)


@dataclass
class StreamRunState:
    """单轮 Agent 流式执行期间的累计状态。"""

    accumulated_chunk: AIMessageChunk | None = None
    streamed_tool_traces: list[ToolTrace] = field(default_factory=list)
    ui_parts: list[ChatMessagePart] = field(default_factory=list)
    seen_called: set[str] = field(default_factory=set)
    seen_returned: set[str] = field(default_factory=set)
    text_part_index: int = 0
    reasoning_part_index: int = 0


class AgentStreamService:
    """协调单轮 Agent astream 执行并累计流式状态。"""

    def __init__(self, runtime_service: AgentRuntimeService) -> None:
        self._runtime_service = runtime_service

    async def stream_agent_run(
        self,
        *,
        thread_id: str,
        agent_input: dict[str, Any] | Any,
        checkpoint_id: str | None,
        model_profile_key: str,
        state: StreamRunState,
        agent_context: AgentRequestContext,
        assistant_message_id: str = "assistant-message",
        version_id: str = "assistant-version",
        on_assistant_text_chunk: Callable[[str], None] | None = None,
    ):
        """执行一次底层 Agent 流并累积结果。"""
        runtime = self._runtime_service.require_runtime()

        configurable: dict[str, Any] = {
            "thread_id": thread_id,
            **get_llm_configurable(model_profile_key),
        }
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        async for part in runtime.agent.astream(
            agent_input,
            config={"configurable": configurable},
            context=agent_context,
            stream_mode=["messages", "updates"],
            version="v2",
        ):
            if not isinstance(part, dict):
                continue

            part_type = str(part.get("type", "")).strip()
            raw_data = part.get("data")

            if part_type == "messages":
                message_chunk, _stream_meta = _extract_ai_chunk_event(raw_data)
                if message_chunk is not None:
                    if state.accumulated_chunk is None:
                        state.accumulated_chunk = message_chunk
                    else:
                        state.accumulated_chunk = state.accumulated_chunk + message_chunk
                    if on_assistant_text_chunk is not None:
                        chunk_text = _content_to_text(message_chunk.content)
                        if chunk_text.strip():
                            on_assistant_text_chunk(chunk_text)
                    for tool_payload in _chunk_to_tool_start_payloads(
                        state,
                        assistant_message_id=assistant_message_id,
                        version_id=version_id,
                        chunk=message_chunk,
                    ):
                        yield "tool.start", tool_payload.model_dump()
                    for delta_payload in _chunk_to_part_deltas(
                        state,
                        assistant_message_id=assistant_message_id,
                        version_id=version_id,
                        chunk=message_chunk,
                    ):
                        yield "part.delta", delta_payload.model_dump()

            if part_type == "updates":
                for _, _, trace in _extract_tool_events(
                    raw_data,
                    seen_called=state.seen_called,
                    seen_returned=state.seen_returned,
                ):
                    state.streamed_tool_traces.append(trace)
                    tool_payload = _trace_to_tool_part_payload(
                        state,
                        assistant_message_id=assistant_message_id,
                        version_id=version_id,
                        trace=trace,
                    )
                    if tool_payload is not None:
                        yield "tool.start" if trace.phase == "called" else "tool.done", tool_payload.model_dump()


def _extract_ai_chunk_event(payload: Any) -> tuple[AIMessageChunk | None, dict[str, Any]]:
    """从 LangGraph `messages` 事件中提取 `AIMessageChunk` 与元信息。"""
    if isinstance(payload, AIMessageChunk):
        return payload, {}

    if not isinstance(payload, tuple):
        return None, {}

    chunk: AIMessageChunk | None = None
    metadata: dict[str, Any] = {}
    for item in payload:
        if isinstance(item, AIMessageChunk) and chunk is None:
            chunk = item
            continue
        if isinstance(item, dict):
            metadata.update(item)

    return chunk, metadata


def _extract_tool_events(
    payload: Any,
    *,
    seen_called: set[str],
    seen_returned: set[str],
):
    """从 LangGraph `updates` 中提取工具调用/返回事件并去重。"""
    for message in _iter_base_messages(payload):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if not isinstance(call, dict):
                    continue
                tool_name = str(call.get("name", "unknown"))
                args = call.get("args", {})
                call_id = str(call.get("id") or _stable_call_key(tool_name, args))
                if call_id in seen_called:
                    continue
                seen_called.add(call_id)
                trace = ToolTrace(phase="called", tool_name=tool_name, payload=args)
                trace.tool_call_id = call_id
                trace.result_status = None
                yield "tool_called", {"tool_name": tool_name, "payload": args}, trace
            continue

        if not isinstance(message, ToolMessage):
            continue

        tool_name = str(message.name or "unknown")
        payload_text = _content_to_text(message.content)
        returned_key = str(message.tool_call_id or f"{tool_name}:{payload_text}")
        if returned_key in seen_returned:
            continue
        seen_returned.add(returned_key)

        trace = ToolTrace(
            phase="returned",
            tool_name=tool_name,
            payload=_tool_message_payload(message),
            tool_call_id=str(message.tool_call_id or returned_key),
            result_status="error" if str(getattr(message, "status", "")).lower() == "error" else "success",
        )
        yield "tool_returned", {"tool_name": tool_name, "payload": payload_text}, trace


def _iter_base_messages(payload: Any):
    """递归遍历负载中的 LangChain BaseMessage。"""
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


def _chunk_to_part_deltas(
    state: StreamRunState,
    *,
    assistant_message_id: str,
    version_id: str,
    chunk: AIMessageChunk,
) -> list[PartDeltaPayload]:
    """把 AI chunk 转换为前端 UI text/reasoning 增量。"""
    payloads: list[PartDeltaPayload] = []
    reasoning_text = _message_reasoning_text(chunk)
    if reasoning_text:
        part = _append_text_like_part(state, part_type="reasoning", delta=reasoning_text)
        payloads.append(
            PartDeltaPayload(
                message_id=assistant_message_id,
                version_id=version_id,
                part_id=part.id,
                part_type="reasoning",
                text_delta=reasoning_text,
            )
        )

    chunk_text = _content_to_text(chunk.content)
    if chunk_text:
        part = _append_text_like_part(state, part_type="text", delta=chunk_text)
        payloads.append(
            PartDeltaPayload(
                message_id=assistant_message_id,
                version_id=version_id,
                part_id=part.id,
                part_type="text",
                text_delta=chunk_text,
            )
        )
    return payloads


def _chunk_to_tool_start_payloads(
    state: StreamRunState,
    *,
    assistant_message_id: str,
    version_id: str,
    chunk: AIMessageChunk,
) -> list[ToolPartPayload]:
    """从 AI chunk 的 tool call 增量中尽早构建 running 工具 part。"""
    payloads: list[ToolPartPayload] = []
    for call in _iter_chunk_tool_calls(chunk):
        tool_name = str(call.get("name") or "").strip()
        if not tool_name:
            continue

        tool_call_id = str(call.get("id") or _stable_call_key(tool_name, call.get("index", "")))
        payload = call.get("args", {})
        trace = ToolTrace(
            phase="called",
            tool_name=tool_name,
            payload=payload if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None else str(payload),
            tool_call_id=tool_call_id,
            result_status=None,
        )
        is_first_seen = tool_call_id not in state.seen_called
        state.seen_called.add(tool_call_id)
        if is_first_seen:
            state.streamed_tool_traces.append(trace)
        tool_payload = _trace_to_tool_part_payload(
            state,
            assistant_message_id=assistant_message_id,
            version_id=version_id,
            trace=trace,
        )
        if tool_payload is not None:
            payloads.append(tool_payload)
    return payloads


def _iter_chunk_tool_calls(chunk: AIMessageChunk):
    """提取 chunk 中当前可识别的工具调用。"""
    yielded_ids: set[str] = set()

    for call in getattr(chunk, "tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        tool_name = call.get("name")
        if not tool_name:
            continue
        call_id = str(call.get("id") or _stable_call_key(str(tool_name), call.get("args", {})))
        yielded_ids.add(call_id)
        yield {
            "id": call_id,
            "name": tool_name,
            "args": call.get("args", {}),
            "index": call.get("index"),
        }

    for call in getattr(chunk, "tool_call_chunks", []) or []:
        if not isinstance(call, dict):
            continue
        tool_name = call.get("name")
        if not tool_name:
            continue
        call_id = str(call.get("id") or _stable_call_key(str(tool_name), call.get("index", "")))
        if call_id in yielded_ids:
            continue
        raw_args = call.get("args", {})
        args: Any = raw_args
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                args = raw_args
        yield {
            "id": call_id,
            "name": tool_name,
            "args": args,
            "index": call.get("index"),
        }


def _append_text_like_part(
    state: StreamRunState,
    *,
    part_type: str,
    delta: str,
) -> ChatTextPart | ChatReasoningPart:
    last_part = state.ui_parts[-1] if state.ui_parts else None
    if last_part is not None and last_part.type == part_type:
        last_part.text += delta  # type: ignore[attr-defined]
        last_part.status = "streaming"  # type: ignore[attr-defined]
        return last_part  # type: ignore[return-value]

    if part_type == "reasoning":
        state.reasoning_part_index += 1
        part = ChatReasoningPart(id=f"reasoning-{state.reasoning_part_index}", text=delta, status="streaming")
    else:
        state.text_part_index += 1
        part = ChatTextPart(id=f"text-{state.text_part_index}", text=delta, status="streaming")
    state.ui_parts.append(part)
    return part


def _trace_to_tool_part_payload(
    state: StreamRunState,
    *,
    assistant_message_id: str,
    version_id: str,
    trace: ToolTrace,
) -> ToolPartPayload | None:
    """把工具调用轨迹转换为前端可原地更新的 tool part。"""
    tool_call_id = trace.tool_call_id or _stable_call_key(trace.tool_name, trace.payload)
    existing = next((part for part in state.ui_parts if part.type == "tool" and part.tool_call_id == tool_call_id), None)
    if trace.phase == "called":
        if existing is None:
            existing = ChatToolPart(
                id=f"tool-{tool_call_id}",
                tool_call_id=tool_call_id,
                tool_name=trace.tool_name,
                input=trace.payload,
                status="running",
            )
            state.ui_parts.append(existing)
        else:
            existing.tool_name = trace.tool_name
            existing.input = trace.payload
            existing.status = "running"
        return ToolPartPayload(message_id=assistant_message_id, version_id=version_id, part=existing)

    if existing is None:
        existing = ChatToolPart(
            id=f"tool-{tool_call_id}",
            tool_call_id=tool_call_id,
            tool_name=trace.tool_name,
            status="success",
        )
        state.ui_parts.append(existing)
    existing.tool_name = trace.tool_name
    existing.output = trace.payload
    existing.status = "error" if trace.result_status == "error" else "success"
    return ToolPartPayload(message_id=assistant_message_id, version_id=version_id, part=existing)


def _message_reasoning_text(message: AIMessage | AIMessageChunk | None) -> str:
    if message is None:
        return ""
    reasoning_from_kwargs = message.additional_kwargs.get("reasoning_content")
    if isinstance(reasoning_from_kwargs, str) and reasoning_from_kwargs:
        return reasoning_from_kwargs
    content = message.content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type not in {"reasoning", "reasoning_content"}:
            continue
        for key in ("reasoning", "reasoning_content", "text"):
            value = item.get(key)
            if isinstance(value, str) and value:
                chunks.append(value)
    return "".join(chunks)


def _stable_call_key(tool_name: str, args: Any) -> str:
    """为缺失 call_id 的工具调用生成稳定去重键。"""
    try:
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        args_repr = str(args)
    return f"{tool_name}:{args_repr}"


def _serialize_stream_part(part: dict[str, Any]) -> dict[str, Any]:
    """将 LangGraph `StreamPart` 递归转换为可 JSON 序列化结构。"""
    return _serialize_native_value(part)


def _serialize_native_value(value: Any) -> Any:
    """递归序列化 LangChain / LangGraph 原生对象。"""
    if isinstance(value, BaseMessage):
        return message_to_dict(value)
    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value):
        return _serialize_native_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize_native_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_native_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_native_value(item) for item in value]
    if isinstance(value, set):
        return [_serialize_native_value(item) for item in value]
    return value
