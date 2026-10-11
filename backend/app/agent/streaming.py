"""Agent 流式执行与事件累计（LangGraph v3 typed projections 驱动）。

架构概述
--------
消费 ``astream_events(version="v3")`` 的三个 typed 投影，各司其职：

================  ===================================================
投影               用途
================  ===================================================
``messages``      每次 LLM 调用的 text / reasoning 增量 → part.delta
``tool_calls``    工具执行生命周期；``call.output`` 是序列化后的
                  ToolMessage（含 content 与 artifact）→ tool.start /
                  tool.done，卡片与引用在 tool.done 时一次到位
================  ===================================================

两个投影并发消费、经一个 asyncio.Queue 汇流，保持事件的全局到达顺序。
相比旧的"裸协议事件 + 手写去重/快照遍历"实现，生命周期事件由投影保证
每调用恰好一次（started/finished/error），无需 seen_* 去重集合；
元组解包、updates 快照消息遍历等补丁逻辑全部删除。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent.cards import extract_cards_from_trace
from app.agent.context import AgentRequestContext
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

    assistant_text: str = ""
    reasoning_text: str = ""
    streamed_tool_traces: list[ToolTrace] = field(default_factory=list)
    ui_parts: list[ChatMessagePart] = field(default_factory=list)
    text_part_index: int = 0
    reasoning_part_index: int = 0
    citation_sources: list[CitationSource] = field(default_factory=list)


class AgentStreamService:
    """协调单轮 Agent 流式执行并累计流式状态。"""

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
        """执行一次底层 Agent 流并累计结果。

        每个 yield 都是一个 ``(event_name, payload_dict)`` 二元组，事件类型：
        ``part.delta`` / ``tool.start`` / ``tool.done``。
        """
        runtime = self._runtime_service.require_runtime()
        executor = agent if agent is not None else runtime.agent

        configurable: dict[str, Any] = {"thread_id": thread_id}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        stream = await executor.astream_events(
            agent_input,
            config={"configurable": configurable},
            context=agent_context,
            version="v3",
        )

        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        async def consume_messages() -> None:
            async for message in stream.messages:
                async for delta in message.reasoning:
                    if delta:
                        state.reasoning_text += delta
                        for payload in self._text_delta_payloads(
                            state, "reasoning", delta, assistant_message_id, version_id
                        ):
                            await queue.put(("part.delta", payload.model_dump()))
                async for delta in message.text:
                    if delta:
                        state.assistant_text += delta
                        if on_assistant_text_chunk is not None and delta.strip():
                            on_assistant_text_chunk(delta)
                        for payload in self._text_delta_payloads(
                            state, "text", delta, assistant_message_id, version_id
                        ):
                            await queue.put(("part.delta", payload.model_dump()))

        async def consume_tool_calls() -> None:
            async for call in stream.tool_calls:
                called_trace = ToolTrace(
                    phase="called",
                    tool_name=call.tool_name,
                    payload=call.input or {},
                    tool_call_id=call.tool_call_id,
                    result_status=None,
                )
                state.streamed_tool_traces.append(called_trace)
                # 工具来临前收尾仍 streaming 的 reasoning/text part
                for payload in _seal_payloads(
                    _seal_streaming_text_like_parts(state), assistant_message_id, version_id
                ):
                    await queue.put(("part.delta", payload.model_dump()))
                await queue.put(
                    (
                        "tool.start",
                        ToolPartPayload(
                            message_id=assistant_message_id,
                            version_id=version_id,
                            part=self._upsert_tool_part(state, called_trace),
                        ).model_dump(),
                    )
                )

                async for _delta in call.output_deltas:  # 工具输出不做逐字流式
                    pass

                content, artifact, errored = _split_tool_output(call)
                payload = artifact if artifact is not None else content
                done_trace = ToolTrace(
                    phase="returned",
                    tool_name=call.tool_name,
                    payload=payload,
                    tool_call_id=call.tool_call_id,
                    result_status="error" if errored else "success",
                )
                state.streamed_tool_traces.append(done_trace)
                part = self._upsert_tool_part(state, done_trace)
                sources = _extract_citation_sources_from_trace(done_trace)
                if sources:
                    part.sources = sources
                    state.citation_sources.extend(sources)
                cards = extract_cards_from_trace(done_trace)
                if cards:
                    part.cards = cards
                await queue.put(
                    (
                        "tool.done",
                        ToolPartPayload(
                            message_id=assistant_message_id, version_id=version_id, part=part
                        ).model_dump(),
                    )
                )

        async def run_consumer(fn: Callable[[], Any]) -> None:
            try:
                await fn()
            finally:
                await queue.put(None)

        consumers = asyncio.gather(
            run_consumer(consume_messages),
            run_consumer(consume_tool_calls),
        )
        try:
            done_count = 0
            while done_count < 2:
                item = await queue.get()
                if item is None:
                    done_count += 1
                    continue
                yield item
        finally:
            await consumers

    # ---- helpers ----

    def _text_delta_payloads(
        self, state: StreamRunState, part_type: str, delta: str, message_id: str, version_id: str
    ) -> list[PartDeltaPayload]:
        payloads: list[PartDeltaPayload] = []
        part, sealed = _append_text_like_part(state, part_type=part_type, delta=delta)
        payloads.extend(_seal_payloads(sealed, message_id, version_id))
        payloads.append(
            PartDeltaPayload(
                message_id=message_id,
                version_id=version_id,
                part_id=part.id,
                part_type=part_type,
                text_delta=delta,
            )
        )
        return payloads

    @staticmethod
    def _upsert_tool_part(state: StreamRunState, trace: ToolTrace) -> ChatToolPart:
        """按 tool_call_id 找到（或创建）tool part 并写入本阶段状态。"""
        tool_call_id = trace.tool_call_id or trace.tool_name
        existing = next(
            (
                part
                for part in state.ui_parts
                if part.type == "tool" and part.tool_call_id == tool_call_id
            ),
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
            return existing

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
        return existing


def _split_tool_output(call: Any) -> tuple[Any, Any, bool]:
    """把 tool_calls 投影的完成态拆为 (content, artifact, errored)。

    ``call.output`` 为 ToolMessage（或其序列化 dict）；``call.error`` 存在时为错误文本。
    """
    if call.error is not None:
        return str(call.error), None, True
    output = call.output
    if isinstance(output, dict):
        return (
            output.get("content"),
            output.get("artifact"),
            str(output.get("status", "")).lower() == "error",
        )
    return (
        getattr(output, "content", output),
        getattr(output, "artifact", None),
        str(getattr(output, "status", "") or "").lower() == "error",
    )


# ---------------------------------------------------------------------------
# Part 状态维护
# ---------------------------------------------------------------------------


def _seal_streaming_text_like_parts(state: StreamRunState) -> list[ChatTextPart | ChatReasoningPart]:
    """把仍 streaming 的 reasoning / text part 标记 completed（防止 chip 卡"思考中"）。"""
    sealed: list[ChatTextPart | ChatReasoningPart] = []
    for part in state.ui_parts:
        if part.type in {"reasoning", "text"} and part.status == "streaming":
            part.status = "completed"
            sealed.append(part)
    return sealed


def _seal_payloads(
    sealed: list[ChatTextPart | ChatReasoningPart], message_id: str, version_id: str
) -> list[PartDeltaPayload]:
    return [
        PartDeltaPayload(
            message_id=message_id,
            version_id=version_id,
            part_id=part.id,
            part_type=part.type,
            text_delta="",
            status="completed",
        )
        for part in sealed
    ]


def _append_text_like_part(
    state: StreamRunState, *, part_type: str, delta: str
) -> tuple[ChatTextPart | ChatReasoningPart, list[ChatTextPart | ChatReasoningPart]]:
    """追加一段 text / reasoning；类型切换时先收尾旧 part。"""
    sealed: list[ChatTextPart | ChatReasoningPart] = []
    last_part = state.ui_parts[-1] if state.ui_parts else None
    if last_part is not None and last_part.type == part_type:
        last_part.text += delta
        last_part.status = "streaming"
        return last_part, sealed

    sealed = _seal_streaming_text_like_parts(state)
    if part_type == "reasoning":
        state.reasoning_part_index += 1
        part = ChatReasoningPart(id=f"reasoning-{state.reasoning_part_index}", text=delta, status="streaming")
    else:
        state.text_part_index += 1
        part = ChatTextPart(id=f"text-{state.text_part_index}", text=delta, status="streaming")
    state.ui_parts.append(part)
    return part, sealed


# ---------------------------------------------------------------------------
# 引用来源提取
# ---------------------------------------------------------------------------

_SRC_MARKER_RE = re.compile(r"\[src-(\d+)\]")

_CITATION_URL_FIELDS: tuple[str, ...] = (
    "bookingUrl",
    "booking_url",
    "url",
    "link",
    "href",
    "sourceUrl",
    "source_url",
)

_CITATION_TITLE_FIELDS: tuple[str, ...] = (
    "title",
    "name",
    "hotelName",
    "hotel_name",
    "displayName",
    "display_name",
)


def _pick_first_string(item: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_citation_from_dict(item: Mapping[str, Any]) -> CitationSource | None:
    url = _pick_first_string(item, _CITATION_URL_FIELDS)
    if url is None:
        return None
    title = _pick_first_string(item, _CITATION_TITLE_FIELDS) or url
    return CitationSource(url=url, title=title)


def _extract_citation_sources_from_trace(trace: ToolTrace) -> list[CitationSource]:
    """从工具返回 payload 中提取引用来源（领域无关的形状匹配）。"""
    payload = trace.payload
    if payload is None:
        return []
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
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                citation = _coerce_citation_from_dict(item)
                if citation is not None:
                    sources.append(citation)
    return sources


def resolve_annotations_from_text(text: str, sources: list[CitationSource]) -> list[CitationSource]:
    """扫描文本中的 [src-N] 标记，生成带 start_index/end_index 的 annotations。"""
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
