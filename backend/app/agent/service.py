"""旅行 Agent 服务层。

该模块负责：
1. 初始化 LangGraph Agent 运行时；
2. 提供会话管理（SQLite 持久化）；
3. 提供聊天流式执行能力（SSE 事件由 API 层封装）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.llm.provider import build_chat_model
from app.mcp.client import MCPToolBundle, load_mcp_tools
from app.mcp.config import load_mcp_connections
from app.memory.runtime import build_memory_runtime
from app.memory.sqlite_store import ChatSQLiteStore
from app.prompt.system import TRAVEL_SYSTEM_PROMPT
from app.schemas.chat import (
    ChatDebugInfo,
    ChatInvokeRequest,
    ChatInvokeResponse,
    SessionDetail,
    SessionSummary,
    StreamChunkMetaPayload,
    StreamChunkPayload,
    StreamStartPayload,
    StreamTokenPayload,
    StreamToolPayload,
    StructuredTravelPlan,
    ToolTrace,
)
from app.tool.local_tools import get_local_tools


@dataclass
class AgentRuntime:
    """Agent 运行时容器。"""

    graph: Any
    mcp_bundle: MCPToolBundle
    local_tool_names: list[str]
    checkpointer: AsyncSqliteSaver


class TravelAgentService:
    """旅行 Agent 业务服务。"""

    def __init__(self, mcp_config_path: Path, sqlite_db_path: Path) -> None:
        """初始化服务。

        Args:
            mcp_config_path: MCP 配置文件路径。
            sqlite_db_path: 本地聊天 SQLite 文件路径。
        """
        self._mcp_config_path = mcp_config_path
        self._sqlite_db_path = sqlite_db_path
        self._runtime: AgentRuntime | None = None
        self._chat_store = ChatSQLiteStore(sqlite_db_path)

    async def startup(self) -> None:
        """初始化 Agent 运行时。"""
        if self._runtime is not None:
            return

        local_tools = get_local_tools()
        connections = load_mcp_connections(self._mcp_config_path)
        mcp_bundle = await load_mcp_tools(connections)

        checkpointer, store = await build_memory_runtime(self._sqlite_db_path)
        model = build_chat_model()
        graph = create_agent(
            model=model,
            tools=[*local_tools, *mcp_bundle.tools],
            system_prompt=TRAVEL_SYSTEM_PROMPT,
            checkpointer=checkpointer,
            store=store,
            response_format=StructuredTravelPlan,
        )

        self._runtime = AgentRuntime(
            graph=graph,
            mcp_bundle=mcp_bundle,
            local_tool_names=[tool.name for tool in local_tools],
            checkpointer=checkpointer,
        )

    async def shutdown(self) -> None:
        """关闭运行时关联的 MCP 客户端连接。"""
        if self._runtime is None:
            return

        if self._runtime.mcp_bundle.client:
            close_method = getattr(self._runtime.mcp_bundle.client, "close", None)
            if close_method:
                maybe_result = close_method()
                if hasattr(maybe_result, "__await__"):
                    await maybe_result

        await self._runtime.checkpointer.conn.close()
        self._runtime = None

    def runtime_snapshot(self) -> dict[str, Any]:
        """返回当前运行时状态快照，用于健康检查。"""
        if self._runtime is None:
            return {
                "ready": False,
                "mcp_connected_servers": [],
                "mcp_errors": [],
                "local_tools": [],
                "mcp_tools": [],
            }

        return {
            "ready": True,
            "mcp_connected_servers": self._runtime.mcp_bundle.connected_servers,
            "mcp_errors": self._runtime.mcp_bundle.errors,
            "local_tools": self._runtime.local_tool_names,
            "mcp_tools": [getattr(tool, "name", "unknown") for tool in self._runtime.mcp_bundle.tools],
        }

    def list_sessions(self) -> list[SessionSummary]:
        """返回会话摘要列表。"""
        return self._chat_store.list_sessions()

    def get_session_detail(self, thread_id: str) -> SessionDetail | None:
        """返回会话详情。"""
        return self._chat_store.get_session_detail(thread_id)

    def rename_session(self, thread_id: str, title: str) -> SessionSummary | None:
        """重命名会话。"""
        return self._chat_store.rename_session(thread_id, title)

    async def delete_session(self, thread_id: str) -> bool:
        """删除会话。"""
        deleted = self._chat_store.delete_session(thread_id)
        if deleted and self._runtime is not None:
            await self._runtime.checkpointer.adelete_thread(thread_id)
        return deleted

    async def stream_invoke(self, request: ChatInvokeRequest):
        """执行流式聊天并产出领域事件。

        在流式前先写入用户消息；在流式结束后写入助手消息，确保会话可重启恢复。
        """
        if self._runtime is None:
            await self.startup()

        assert self._runtime is not None

        self._chat_store.append_user_message(request.thread_id, request.user_message)
        model_messages = [HumanMessage(content=request.user_message)]

        yield "start", StreamStartPayload(
            thread_id=request.thread_id,
            started_at=_utc_now_iso(),
        ).model_dump()

        streamed_tool_traces: list[ToolTrace] = []
        seen_called: set[str] = set()
        seen_returned: set[str] = set()
        latest_values: dict[str, Any] | None = None
        accumulated_chunk: AIMessageChunk | None = None
        token_sequence = 0

        async for mode, chunk in self._runtime.graph.astream(
            {"messages": model_messages},
            config={"configurable": {"thread_id": request.thread_id}},
            stream_mode=["messages", "updates", "values"],
        ):
            if mode == "messages":
                message_chunk, stream_meta = _extract_ai_chunk_event(chunk)
                if message_chunk is None:
                    continue

                token_sequence += 1
                if accumulated_chunk is None:
                    accumulated_chunk = message_chunk
                else:
                    accumulated_chunk = accumulated_chunk + message_chunk

                yield "token", StreamTokenPayload(
                    chunk=_serialize_chunk(message_chunk),
                    meta=StreamChunkMetaPayload(
                        node=_extract_chunk_node(stream_meta),
                        sequence=token_sequence,
                        emitted_at=_utc_now_iso(),
                    ),
                ).model_dump()
                continue

            if mode == "updates":
                for event_name, event_payload, trace in _extract_tool_events(
                    chunk, seen_called=seen_called, seen_returned=seen_returned
                ):
                    streamed_tool_traces.append(trace)
                    yield event_name, event_payload
                continue

            if mode == "values" and isinstance(chunk, dict):
                latest_values = chunk

        final_response = _build_final_response(
            latest_values=latest_values,
            accumulated_chunk=accumulated_chunk,
            streamed_tool_traces=streamed_tool_traces,
            runtime=self._runtime,
        )

        self._chat_store.append_assistant_message(
            request.thread_id,
            final_response.assistant_message,
            itinerary=[item.model_dump() for item in final_response.itinerary],
            followups=list(final_response.followups),
            debug=final_response.debug.model_dump(),
        )

        yield "final", final_response.model_dump()


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间戳。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


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


def _extract_chunk_node(metadata: dict[str, Any]) -> str | None:
    """提取 chunk 所在节点名。"""
    for key in ("langgraph_node", "node", "source"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _serialize_chunk(chunk: AIMessageChunk) -> StreamChunkPayload:
    """序列化 `AIMessageChunk` 到 API 负载。"""
    return StreamChunkPayload(
        id=chunk.id,
        type=chunk.type,
        content=chunk.content,
        name=chunk.name,
        chunk_position=getattr(chunk, "chunk_position", None),
        tool_call_chunks=list(chunk.tool_call_chunks or []),
        tool_calls=list(chunk.tool_calls or []),
        invalid_tool_calls=list(chunk.invalid_tool_calls or []),
        usage_metadata=chunk.usage_metadata,
        response_metadata=dict(chunk.response_metadata or {}),
        additional_kwargs=dict(chunk.additional_kwargs or {}),
    )


def _build_final_response(
    *,
    latest_values: dict[str, Any] | None,
    accumulated_chunk: AIMessageChunk | None,
    streamed_tool_traces: list[ToolTrace],
    runtime: AgentRuntime,
) -> ChatInvokeResponse:
    """根据流式过程构建最终响应对象。"""
    values = latest_values if isinstance(latest_values, dict) else {}
    messages = _extract_state_messages(values.get("messages"))

    assistant_from_state = _extract_latest_ai_content(messages).strip()
    assistant_from_chunk = _content_to_text(accumulated_chunk.content).strip() if accumulated_chunk else ""
    assistant_seed = assistant_from_state or assistant_from_chunk

    structured = _normalize_structured_plan(values.get("structured_response"), assistant_seed)
    traces_from_state = _extract_tool_traces(messages)
    final_tool_traces = traces_from_state or streamed_tool_traces

    assistant_message = assistant_seed or structured.summary

    return ChatInvokeResponse(
        assistant_message=assistant_message,
        itinerary=structured.itinerary,
        followups=structured.followups,
        debug=ChatDebugInfo(
            tool_traces=final_tool_traces,
            mcp_connected_servers=runtime.mcp_bundle.connected_servers,
            mcp_errors=runtime.mcp_bundle.errors,
        ),
    )


def _extract_state_messages(payload: Any) -> list[BaseMessage]:
    """从 LangGraph values 中抽取消息列表。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, BaseMessage)]
    return list(_iter_base_messages(payload))


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
                yield "tool_called", StreamToolPayload(tool_name=tool_name, payload=args).model_dump(), trace
            continue

        if not isinstance(message, ToolMessage):
            continue

        tool_name = str(message.name or "unknown")
        payload_text = _content_to_text(message.content)
        returned_key = str(message.tool_call_id or f"{tool_name}:{payload_text}")
        if returned_key in seen_returned:
            continue
        seen_returned.add(returned_key)

        trace = ToolTrace(phase="returned", tool_name=tool_name, payload=payload_text)
        yield (
            "tool_returned",
            StreamToolPayload(tool_name=tool_name, payload=payload_text).model_dump(),
            trace,
        )


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


def _stable_call_key(tool_name: str, args: Any) -> str:
    """为缺失 call_id 的工具调用生成稳定去重键。"""
    try:
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        args_repr = str(args)
    return f"{tool_name}:{args_repr}"


def _normalize_structured_plan(raw_plan: Any, assistant_message: str) -> StructuredTravelPlan:
    """将结构化计划结果归一化为 `StructuredTravelPlan`。"""
    if isinstance(raw_plan, StructuredTravelPlan):
        return raw_plan
    if isinstance(raw_plan, dict):
        return StructuredTravelPlan.model_validate(raw_plan)
    return StructuredTravelPlan(summary=assistant_message, itinerary=[], followups=[])


def _extract_latest_ai_content(messages: list[BaseMessage]) -> str:
    """从消息列表中提取最新一条 `AIMessage` 文本。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _content_to_text(message.content)
    return ""


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
                        )
                    )
            continue

        if isinstance(message, ToolMessage):
            traces.append(
                ToolTrace(
                    phase="returned",
                    tool_name=str(message.name or "unknown"),
                    payload=_content_to_text(message.content),
                )
            )

    return traces


def _content_to_text(content: Any) -> str:
    """将消息 content 统一归一化为字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            else:
                chunks.append(str(item))
        return "\n".join(chunks).strip()
    if content is None:
        return ""
    return str(content)
