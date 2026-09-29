"""Agent 流式执行与事件累计。

架构概述（LangGraph 事件流 v3，``astream_events(version="v3")``）
---------------------------------------------------------------
消费裸协议事件流（单迭代器、全局有序），关注两个通道：

* **messages**: content-block 协议的模型输出。``content-block-delta`` 事件中
  ``text-delta`` → 可见文本增量，``reasoning-delta`` → 思考增量。
* **values**: 每个图节点结束后的完整状态快照。
    - model 节点结束 → 完整 ``AIMessage`` (含完整 ``tool_calls``)
    - tools 节点结束 → 完整 ``ToolMessage`` (含执行结果)

通道分工：

================  ===========================================
信息类型             来源
================  ===========================================
LLM 文字 / 思考     ``messages`` 的 content-block 增量
工具调用决定        ``values`` 快照的 ``AIMessage.tool_calls``
工具执行结果        ``values`` 快照的 ``ToolMessage``
================  ===========================================

工具调用入参以前曾尝试通过 messages 流的 ``tool_call_chunks`` 流式拼装出"入参
逐字打字"的视觉效果，但那条路径会与快照通道的同一调用 id 撞车，造成
``tool.start`` 重复触发、``status`` 被反复重置。当前实现**只通过 ``values``
快照触发工具事件**，牺牲了入参流式动画(也就 1-2 秒的过渡)，换来事件流的
线性、可推理。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, message_to_dict
from pydantic import BaseModel

from app.agent.cards import extract_cards_from_trace
from app.agent.context import AgentRequestContext
from app.agent.presentation import _content_to_text, _tool_message_payload
from app.agent.runtime import AgentRuntimeService
from app.schemas.chat import (
    ChatMessagePart,
    ChatReasoningPart,
    ChatTextPart,
    ChatToolPart,
    CitationSource,
    PartDeltaPayload,
    ToolPartPayload,
    ToolTrace,
)


@dataclass
class StreamRunState:
    """单轮 Agent 流式执行期间的累计状态。"""

    # v3 messages 通道的可见文本 / 思考增量累计，供 build_final_response 与
    # 停止场景使用。工具调用判定**不**用它们，改由 values 快照直接给出完整消息。
    assistant_text: str = ""
    reasoning_text: str = ""
    streamed_tool_traces: list[ToolTrace] = field(default_factory=list)
    ui_parts: list[ChatMessagePart] = field(default_factory=list)
    seen_called: set[str] = field(default_factory=set)
    seen_returned: set[str] = field(default_factory=set)
    text_part_index: int = 0
    reasoning_part_index: int = 0
    citation_sources: list[CitationSource] = field(default_factory=list)


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
        agent: Any | None = None,
    ):
        """执行一次底层 Agent 流并累积结果。

        每个 yield 都是一个 ``(event_name, payload_dict)`` 二元组,直接由上层通过
        SSE 转发给前端。事件类型固定为:

        * ``part.delta`` — text/reasoning 片段增量,或片段 sealed (status=completed)。
        * ``tool.start`` — 工具开始执行,带完整入参。
        * ``tool.done`` — 工具执行结束,带完整 output / sources / cards。
        """
        runtime = self._runtime_service.require_runtime()
        executor = agent if agent is not None else runtime.agent

        configurable: dict[str, Any] = {
            "thread_id": thread_id,
        }
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        stream = await executor.astream_events(
            agent_input,
            config={"configurable": configurable},
            context=agent_context,
            version="v3",
        )
        async for event in stream:
            if not isinstance(event, dict):
                continue

            method = str(event.get("method", ""))
            params = event.get("params") or {}
            data = params.get("data")

            if method == "messages":
                # messages 通道：content-block 增量（text-delta / reasoning-delta）。
                # 工具调用块在此被刻意忽略 —— 工具事件由 values 快照唯一触发。
                async for event_name, payload in self._handle_messages_data(
                    data,
                    state=state,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                    on_assistant_text_chunk=on_assistant_text_chunk,
                ):
                    yield event_name, payload

            elif method == "values":
                # values 通道：节点结束的完整状态快照。AIMessage.tool_calls 触发
                # tool.start；ToolMessage 触发 tool.done（去重由 seen_* 保证）。
                async for event_name, payload in self._handle_node_update(
                    data,
                    state=state,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                ):
                    yield event_name, payload

    # ---- handlers ----

    @staticmethod
    async def _handle_messages_data(
        raw_data: Any,
        *,
        state: StreamRunState,
        assistant_message_id: str,
        version_id: str,
        on_assistant_text_chunk: Callable[[str], None] | None,
    ):
        """处理 messages 通道事件：content-block 增量转化为 part.delta。"""
        for item in _iter_messages_data(raw_data):
            event_type = str(item.get("event", ""))
            if event_type != "content-block-delta":
                continue

            delta = item.get("delta") or {}
            delta_type = str(delta.get("type", ""))

            if delta_type == "text-delta":
                delta_text = str(delta.get("text", "") or "")
                if not delta_text:
                    continue
                state.assistant_text += delta_text
                # TTS 等下游需要拿"用户可见文本"的逐字流
                if on_assistant_text_chunk is not None and delta_text.strip():
                    on_assistant_text_chunk(delta_text)
                for payload in _text_delta_payloads(
                    state,
                    part_type="text",
                    delta=delta_text,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                ):
                    yield "part.delta", payload.model_dump()

            elif delta_type == "reasoning-delta":
                delta_text = str(delta.get("reasoning", "") or "")
                if not delta_text:
                    continue
                state.reasoning_text += delta_text
                for payload in _text_delta_payloads(
                    state,
                    part_type="reasoning",
                    delta=delta_text,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                ):
                    yield "part.delta", payload.model_dump()

            elif delta_type == "block-delta":
                # 提供方私有增量（如 Qwen reasoning_content）经 fields 透传
                fields = delta.get("fields") or {}
                reasoning_text = fields.get("reasoning_content") or fields.get("reasoning")
                if isinstance(reasoning_text, str) and reasoning_text:
                    state.reasoning_text += reasoning_text
                    for payload in _text_delta_payloads(
                        state,
                        part_type="reasoning",
                        delta=reasoning_text,
                        assistant_message_id=assistant_message_id,
                        version_id=version_id,
                    ):
                        yield "part.delta", payload.model_dump()

    @staticmethod
    async def _handle_node_update(
        raw_data: Any,
        *,
        state: StreamRunState,
        assistant_message_id: str,
        version_id: str,
    ):
        """处理 values 通道事件: 从节点结束快照中提取工具调用 / 工具返回。"""
        for event_type, _, trace in _extract_tool_events(
            raw_data,
            seen_called=state.seen_called,
            seen_returned=state.seen_returned,
        ):
            state.streamed_tool_traces.append(trace)

            # 工具事件来临前,确保上一段 reasoning/text 已被收尾通知前端,
            # 防止 chip 永远停在 "思考中"。
            if trace.phase == "called":
                for sealed_payload in _seal_payloads(
                    _seal_streaming_text_like_parts(state),
                    assistant_message_id,
                    version_id,
                ):
                    yield "part.delta", sealed_payload.model_dump()

            # 工具返回时提取引用来源,挂到对应 tool part 上(也累计供最终文本锚定)。
            if event_type == "tool_returned":
                sources = _extract_citation_sources_from_trace(trace)
                state.citation_sources.extend(sources)

            tool_payload = _trace_to_tool_part_payload(
                state,
                assistant_message_id=assistant_message_id,
                version_id=version_id,
                trace=trace,
            )
            if tool_payload is None:
                continue

            yield (
                "tool.start" if trace.phase == "called" else "tool.done",
                tool_payload.model_dump(),
            )


# ---------------------------------------------------------------------------
# Event extraction helpers
# ---------------------------------------------------------------------------


def _iter_messages_data(raw_data: Any) -> list[dict[str, Any]]:
    """把 messages 通道事件的 data 归一化为 MessagesData dict 列表。

    实测协议形状为二元组 ``(MessagesData, metadata)``（v3 在 v2 消息元组外保留了
    metadata 位）；文档示例中也有直接给 dict 列表的形态。两种都兼容：
    逐个元素取带 ``event`` 字段的 dict，其余（如完整的 AIMessage 快照）忽略。
    """
    items: list[Any] = list(raw_data) if isinstance(raw_data, (tuple, list)) else [raw_data]
    return [item for item in items if isinstance(item, dict) and "event" in item]


def _extract_tool_events(
    payload: Any,
    *,
    seen_called: set[str],
    seen_returned: set[str],
):
    """从 LangGraph ``updates`` 中提取工具调用/返回事件并去重。

    去重策略:每个 ``call_id`` 只允许产生一次 ``tool_called`` 和一次 ``tool_returned``。
    去重 set 由调用方(``StreamRunState``)提供,跨节点共享。
    """
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


# ---------------------------------------------------------------------------
# Part state mutation helpers
# ---------------------------------------------------------------------------


def _text_delta_payloads(
    state: StreamRunState,
    *,
    part_type: str,
    delta: str,
    assistant_message_id: str,
    version_id: str,
) -> list[PartDeltaPayload]:
    """把一段 text / reasoning 增量转换为前端 UI part.delta 序列。"""
    payloads: list[PartDeltaPayload] = []
    part, sealed = _append_text_like_part(state, part_type=part_type, delta=delta)
    payloads.extend(_seal_payloads(sealed, assistant_message_id, version_id))
    payloads.append(
        PartDeltaPayload(
            message_id=assistant_message_id,
            version_id=version_id,
            part_id=part.id,
            part_type=part_type,
            text_delta=delta,
        )
    )
    return payloads


def _seal_streaming_text_like_parts(state: StreamRunState) -> list[ChatTextPart | ChatReasoningPart]:
    """把当前所有仍处于 streaming 状态的 reasoning / text part 标记为 completed。

    用于流式过程中切换到不同类型 part(例如 reasoning → tool)时收尾上一段,
    避免前端 chip 永远停留在 "思考中"。返回被收尾的 part 列表,便于调用方
    向前端发送状态变更事件。
    """
    sealed: list[ChatTextPart | ChatReasoningPart] = []
    for part in state.ui_parts:
        if part.type in {"reasoning", "text"} and part.status == "streaming":  # type: ignore[union-attr]
            part.status = "completed"  # type: ignore[union-attr]
            sealed.append(part)  # type: ignore[arg-type]
    return sealed


def _seal_payloads(
    sealed: list[ChatTextPart | ChatReasoningPart],
    assistant_message_id: str,
    version_id: str,
) -> list[PartDeltaPayload]:
    """把被收尾的 text-like part 转换为 part.delta 通知(不带文字增量,只更新状态)。"""
    return [
        PartDeltaPayload(
            message_id=assistant_message_id,
            version_id=version_id,
            part_id=part.id,
            part_type=part.type,  # type: ignore[arg-type]
            text_delta="",
            status="completed",
        )
        for part in sealed
    ]


def _append_text_like_part(
    state: StreamRunState,
    *,
    part_type: str,
    delta: str,
) -> tuple[ChatTextPart | ChatReasoningPart, list[ChatTextPart | ChatReasoningPart]]:
    """追加一段 text / reasoning。

    如果上一段 part 是不同类型,会先把所有仍 streaming 的 text-like part 标记为
    completed 并返回它们,调用方据此发送收尾 delta。
    """
    sealed: list[ChatTextPart | ChatReasoningPart] = []
    last_part = state.ui_parts[-1] if state.ui_parts else None
    if last_part is not None and last_part.type == part_type:
        last_part.text += delta  # type: ignore[attr-defined]
        last_part.status = "streaming"  # type: ignore[attr-defined]
        return last_part, sealed  # type: ignore[return-value]

    sealed = _seal_streaming_text_like_parts(state)

    if part_type == "reasoning":
        state.reasoning_part_index += 1
        part = ChatReasoningPart(id=f"reasoning-{state.reasoning_part_index}", text=delta, status="streaming")
    else:
        state.text_part_index += 1
        part = ChatTextPart(id=f"text-{state.text_part_index}", text=delta, status="streaming")
    state.ui_parts.append(part)
    return part, sealed


def _trace_to_tool_part_payload(
    state: StreamRunState,
    *,
    assistant_message_id: str,
    version_id: str,
    trace: ToolTrace,
) -> ToolPartPayload | None:
    """把工具调用轨迹转换为前端可原地更新的 tool part。

    每个 ``call_id`` 在 streaming 期间最多走过两次:
      1. ``called`` —— 创建一个新的 ChatToolPart(status=running),input 来自完整 args dict。
      2. ``returned`` —— 找到该 part,写入 output / status / sources / cards。

    去重已经在 ``_extract_tool_events`` 完成,这里只做状态写入。
    """
    tool_call_id = trace.tool_call_id or _stable_call_key(trace.tool_name, trace.payload)
    existing = next(
        (part for part in state.ui_parts if part.type == "tool" and part.tool_call_id == tool_call_id),
        None,
    )

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
            # 理论上 _extract_tool_events 已去重,不应再次走到这里;为安全起见
            # 仍刷新 tool_name + input,保留 status running。
            existing.tool_name = trace.tool_name
            existing.input = trace.payload
            existing.status = "running"
        return ToolPartPayload(message_id=assistant_message_id, version_id=version_id, part=existing)

    # phase == "returned"
    if existing is None:
        # 同样防御:理论上 called 阶段已经创建过 part,这里兜底。
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

    sources = _extract_citation_sources_from_trace(trace)
    if sources:
        existing.sources = sources

    # 结构化卡片(酒店 / 机票 / 行程 / ...) 由 app.agent.cards 注册的 extractor 决定;
    # streaming 层完全领域无关。
    cards = extract_cards_from_trace(trace)
    if cards:
        existing.cards = cards

    return ToolPartPayload(message_id=assistant_message_id, version_id=version_id, part=existing)


def _stable_call_key(tool_name: str, args: Any) -> str:
    """为缺失 call_id 的工具调用生成稳定去重键。"""
    try:
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        args_repr = str(args)
    return f"{tool_name}:{args_repr}"


# ---------------------------------------------------------------------------
# Native serialization (for legacy diagnostic logging only)
# ---------------------------------------------------------------------------


def _serialize_stream_part(part: dict[str, Any]) -> dict[str, Any]:
    """将 LangGraph ``StreamPart`` 递归转换为可 JSON 序列化结构。"""
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


# ---------------------------------------------------------------------------
# Citation source extraction
# ---------------------------------------------------------------------------

_SRC_MARKER_RE = re.compile(r"\[src-(\d+)\]")

# 工具 payload 中可被识别为"引用 URL"的字段名,按优先级排序。
# 越靠前的字段越具体(如 bookingUrl 是酒店预订深链,比泛 url 更精确)。
# 添加新领域字段时只需在此追加,不需要修改提取逻辑。
_CITATION_URL_FIELDS: tuple[str, ...] = (
    "bookingUrl",
    "booking_url",
    "url",
    "link",
    "href",
    "sourceUrl",
    "source_url",
)

# 工具 payload 中可被识别为"引用标题"的字段名,按优先级排序。
_CITATION_TITLE_FIELDS: tuple[str, ...] = (
    "title",
    "name",
    "hotelName",
    "hotel_name",
    "displayName",
    "display_name",
)


def _pick_first_string(item: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    """按 keys 顺序找出第一个非空字符串值。"""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_citation_from_dict(item: Mapping[str, Any]) -> CitationSource | None:
    """从单条 dict 中提取一条引用;没有 URL 则视为不可引用。"""
    url = _pick_first_string(item, _CITATION_URL_FIELDS)
    if url is None:
        return None
    title = _pick_first_string(item, _CITATION_TITLE_FIELDS) or url
    return CitationSource(url=url, title=title)


def _extract_citation_sources_from_trace(trace: ToolTrace) -> list[CitationSource]:
    """从工具返回的 payload(artifact)中提取引用来源。

    实现是领域无关的:只看 payload 的形状(list[dict] 或 dict 内含 results 数组),
    不针对具体工具或具体业务字段做硬编码。具体哪些字段算"URL/标题"由
    ``_CITATION_URL_FIELDS`` / ``_CITATION_TITLE_FIELDS`` 控制,新增领域只需扩字段表。
    """
    payload = trace.payload
    if payload is None:
        return []

    # If payload is a JSON string, try to parse it
    if isinstance(payload, str):
        payload = payload.strip()
        if payload.startswith(("{", "[")):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return []
        else:
            return []

    sources: list[CitationSource] = []

    # 形状 A:dict 含 "results" 数组(Exa 搜索 / 多数 LLM-style web 工具)
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    citation = _coerce_citation_from_dict(item)
                    if citation is not None:
                        sources.append(citation)
            if sources:
                return sources

    # 形状 B:直接是 list[dict](典型如酒店列表 / POI 列表 / 文档列表)
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                citation = _coerce_citation_from_dict(item)
                if citation is not None:
                    sources.append(citation)
        return sources

    return sources


def resolve_annotations_from_text(
    text: str,
    sources: list[CitationSource],
) -> list[CitationSource]:
    """扫描文本中的 [src-N] 标记,生成带 start_index/end_index 的 annotations。"""
    annotations: list[CitationSource] = []
    for match in _SRC_MARKER_RE.finditer(text):
        idx = int(match.group(1))
        if idx < 1 or idx > len(sources):
            continue
        source = sources[idx - 1]
        annotations.append(
            CitationSource(
                url=source.url,
                title=source.title,
                start_index=match.start(),
                end_index=match.end(),
                cited_text=match.group(0),
            )
        )
    return annotations
