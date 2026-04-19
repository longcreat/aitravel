"""Agent 流式执行与事件累计。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage, message_to_dict
from pydantic import BaseModel

from app.agent.context import AgentRequestContext
from app.agent.presentation import _content_to_text, _iter_base_messages
from app.agent.runtime import AgentRuntimeService
from app.llm.provider import get_llm_configurable
from app.schemas.chat import ChatInterruptPayload, ToolTrace


@dataclass
class StreamRunState:
    """单轮 Agent 流式执行期间的累计状态。"""

    latest_values: dict[str, Any] | None = None
    accumulated_chunk: AIMessageChunk | None = None
    streamed_tool_traces: list[ToolTrace] = field(default_factory=list)
    seen_called: set[str] = field(default_factory=set)
    seen_returned: set[str] = field(default_factory=set)
    interrupt: ChatInterruptPayload | None = None


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
            stream_mode=["messages", "updates", "values"],
            version="v2",
        ):
            if not isinstance(part, dict):
                continue

            part_type = str(part.get("type", "")).strip()
            raw_data = part.get("data")
            interrupt_payload = _extract_interrupt_payload(part)

            if interrupt_payload is not None:
                state.interrupt = interrupt_payload
                yield "interrupt", interrupt_payload.model_dump()
                continue

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

            if part_type == "updates":
                for _, _, trace in _extract_tool_events(
                    raw_data,
                    seen_called=state.seen_called,
                    seen_returned=state.seen_returned,
                ):
                    state.streamed_tool_traces.append(trace)
            elif part_type == "values" and isinstance(raw_data, dict):
                state.latest_values = raw_data

            yield part_type or "message", _serialize_stream_part(part)


def _extract_interrupt_payload(part: dict[str, Any]) -> ChatInterruptPayload | None:
    """从 LangGraph stream part 中提取标准化 interrupt 负载。"""
    interrupts = part.get("interrupts")
    if not interrupts and part.get("type") == "updates":
        raw_data = part.get("data")
        if isinstance(raw_data, dict):
            interrupts = raw_data.get("__interrupt__")

    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None

    first_interrupt = interrupts[0]
    interrupt_id = getattr(first_interrupt, "id", None)
    interrupt_value = getattr(first_interrupt, "value", None)
    if isinstance(first_interrupt, dict):
        interrupt_id = interrupt_id or first_interrupt.get("id")
        interrupt_value = interrupt_value if interrupt_value is not None else first_interrupt.get("value")

    if not interrupt_id:
        return None

    if isinstance(interrupt_value, dict):
        payload = dict(interrupt_value)
    else:
        payload = {"question": str(interrupt_value)}

    payload["interrupt_id"] = str(interrupt_id)
    payload.setdefault("kind", "clarification")
    payload.setdefault("allow_custom_input", True)
    payload.setdefault("suggested_replies", [])
    return ChatInterruptPayload.model_validate(payload)


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
            payload=payload_text,
            tool_call_id=str(message.tool_call_id or returned_key),
            result_status="error" if str(getattr(message, "status", "")).lower() == "error" else "success",
        )
        yield "tool_returned", {"tool_name": tool_name, "payload": payload_text}, trace


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
