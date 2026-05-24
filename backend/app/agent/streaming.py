"""Agent 流式执行与事件累计。

架构概述
---------
LangGraph ``astream(stream_mode=["messages", "updates"])`` 会发出两种事件:

* **messages**: model 节点产生 LLM token 时持续发出 ``AIMessageChunk``。
  ToolMessage 在 tools 节点内部也会作为一条 messages 事件出现一次,但**它的
  完整快照在 updates 中已经覆盖**,所以 messages 阶段我们只取
  ``AIMessageChunk``,用于把 LLM 文字逐字流给前端。
* **updates**: 每个图节点 *结束* 时发出一次,带该节点的完整状态:
    - model 节点结束 → 完整 ``AIMessage`` (含完整 ``tool_calls``)
    - tools 节点结束 → 完整 ``ToolMessage`` (含执行结果)

我们把这两路当成各司其职的通道:

================  ===========================================
信息类型             来源
================  ===========================================
LLM 文字 / 思考     ``messages`` 的 ``AIMessageChunk``
工具调用决定        ``updates`` 的 ``AIMessage.tool_calls``
工具执行结果        ``updates`` 的 ``ToolMessage``
================  ===========================================

工具调用入参以前曾尝试通过 ``messages`` 的 ``tool_call_chunks`` 流式拼装出"入参
逐字打字"的视觉效果,但那条路径会与 ``updates`` 的同一调用 id 撞车,造成
``tool.start`` 重复触发、``status`` 被反复重置。新实现**只通过 ``updates`` 触发
工具事件**,牺牲了入参流式动画(也就 1-2 秒的过渡),换来事件流的线性、可推理。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage, message_to_dict
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

    # `messages` 阶段累积所有 AIMessageChunk,主要给 reasoning_content / text_delta 提供
    # 完整上下文。注意:工具调用判定**不**用它,改由 `updates` 阶段直接给出完整 AIMessage。
    accumulated_chunk: AIMessageChunk | None = None
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

        async for part in executor.astream(
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
                # `messages` 阶段:只处理 model 节点的 LLM token 增量。
                # 工具调用 chunk(tool_call_chunks)在此被刻意忽略 ——
                # 工具事件由后面的 `updates` 分支唯一触发,避免双源竞争。
                async for event_name, payload in self._handle_message_chunk(
                    raw_data,
                    state=state,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                    on_assistant_text_chunk=on_assistant_text_chunk,
                ):
                    yield event_name, payload

            elif part_type == "updates":
                # `updates` 阶段:节点结束的快照。AIMessage.tool_calls 触发 tool.start;
                # ToolMessage 触发 tool.done。
                async for event_name, payload in self._handle_node_update(
                    raw_data,
                    state=state,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                ):
                    yield event_name, payload

    # ---- handlers ----

    @staticmethod
    async def _handle_message_chunk(
        raw_data: Any,
        *,
        state: StreamRunState,
        assistant_message_id: str,
        version_id: str,
        on_assistant_text_chunk: Callable[[str], None] | None,
    ):
        """处理 ``messages`` 流事件: 仅消费 AIMessageChunk,转化为 part.delta。"""
        message_chunk, _meta = _extract_ai_chunk_event(raw_data)
        if message_chunk is None:
            return  # tools 节点的 ToolMessage 等其他形态在此忽略

        # 累积 chunk(便于后续抽取累积态的 reasoning_content 等)
        if state.accumulated_chunk is None:
            state.accumulated_chunk = message_chunk
        else:
            state.accumulated_chunk = state.accumulated_chunk + message_chunk

        # TTS 等下游需要拿"用户可见文本"的逐字流
        if on_assistant_text_chunk is not None:
            chunk_text = _content_to_text(message_chunk.content)
            if chunk_text.strip():
                on_assistant_text_chunk(chunk_text)

        for delta_payload in _chunk_to_part_deltas(
            state,
            assistant_message_id=assistant_message_id,
            version_id=version_id,
            chunk=message_chunk,
        ):
            yield "part.delta", delta_payload.model_dump()

    @staticmethod
    async def _handle_node_update(
        raw_data: Any,
        *,
        state: StreamRunState,
        assistant_message_id: str,
        version_id: str,
    ):
        """处理 ``updates`` 流事件: 从节点结束快照中提取工具调用 / 工具返回。"""
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


def _extract_ai_chunk_event(payload: Any) -> tuple[AIMessageChunk | None, dict[str, Any]]:
    """从 LangGraph ``messages`` 事件中提取 ``AIMessageChunk`` 与元信息。

    LangGraph 将 ``messages`` 事件打包为 ``(message, metadata)`` 元组。我们只关心
    AIMessageChunk(LLM token),其它消息类型(ToolMessage 等)在此忽略 —— 它们
    的完整快照已经由 ``updates`` 阶段处理。
    """
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
        part, sealed = _append_text_like_part(state, part_type="reasoning", delta=reasoning_text)
        payloads.extend(_seal_payloads(sealed, assistant_message_id, version_id))
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
        part, sealed = _append_text_like_part(state, part_type="text", delta=chunk_text)
        payloads.extend(_seal_payloads(sealed, assistant_message_id, version_id))
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
