"""旅行 Agent 服务层。

该模块是后端聊天主链路的核心协调层，主要承担三类职责：
1. 初始化 Agent：把模型、工具、系统提示词、checkpoint 记忆能力组装成可执行 Agent；
2. 管理会话：通过 SQLite 维护会话列表、消息历史与标题等业务数据；
3. 执行聊天：调用 Agent 的流式接口，把 LangGraph 原生事件转成前端可消费的 SSE 数据。
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage, message_to_dict
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

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
    ToolTrace,
)
from app.tool.local_tools import get_local_tools


@dataclass
class AgentRuntime:
    """Agent 运行时容器。

    `create_agent` 返回的是可执行 Agent，对外语义上更适合直接称为 agent；
    其底层执行机制仍由 LangGraph 驱动。
    """

    # Agent 本体：负责接收输入消息并产出 `messages / updates / values` 原生流事件。
    agent: Any
    # MCP 工具加载结果：既包含成功连接的工具，也保留连接错误，方便健康检查时暴露出来。
    mcp_bundle: MCPToolBundle
    # 本地工具名字列表：主要用于健康检查接口和调试信息展示。
    local_tool_names: list[str]
    # LangGraph 官方 SQLite checkpointer：负责会话级状态恢复与回滚。
    checkpointer: AsyncSqliteSaver


class TravelAgentService:
    """旅行 Agent 业务服务。

    这个类把“业务会话存储”和“LangGraph Agent 运行时”绑定在一起：
    - 对外暴露会话管理接口；
    - 对内协调 Agent 执行、状态恢复、工具轨迹提取与异常回滚。
    """

    def __init__(self, mcp_config_path: Path, sqlite_db_path: Path) -> None:
        """初始化服务。

        Args:
            mcp_config_path: MCP 配置文件路径。
            sqlite_db_path: 本地聊天 SQLite 文件路径。
        """
        # MCP 配置文件用于决定需要连接哪些远端工具服务。
        self._mcp_config_path = mcp_config_path
        # 同一个 SQLite 文件既承载业务会话表，也承载 LangGraph checkpoint 表。
        self._sqlite_db_path = sqlite_db_path
        # 运行时在 `startup()` 前为空，首次使用时懒加载初始化。
        self._runtime: AgentRuntime | None = None
        # 业务侧自己的 SQLite 封装，负责会话标题、历史消息和最终回复落库。
        self._chat_store = ChatSQLiteStore(sqlite_db_path)

    async def startup(self) -> None:
        """初始化 Agent 运行时。

        这里会把“模型 + 本地工具 + MCP 工具 + 提示词 + checkpoint”组装成一个可执行 Agent。
        由于服务是单例使用，所以已经初始化过时直接返回，避免重复建立数据库和 MCP 连接。
        """
        # 已经初始化过时直接复用，避免重复建立连接。
        if self._runtime is not None:
            return

        # 先准备本地工具，例如当前时间工具。
        local_tools = get_local_tools()
        # 再从配置文件里读取 MCP 连接定义。
        connections = load_mcp_connections(self._mcp_config_path)
        # 根据连接定义异步加载 MCP 工具。
        mcp_bundle = await load_mcp_tools(connections)

        # 构建 LangGraph 运行时记忆组件；`store` 当前未启用，所以是 `None`。
        checkpointer, store = await build_memory_runtime(self._sqlite_db_path)
        # 根据环境变量创建聊天模型，例如 OpenAI-compatible 的 Qwen / DeepSeek。
        model = build_chat_model()
        # 用 LangChain 官方 `create_agent` 组装出可执行 Agent。
        agent = create_agent(
            model=model,
            # Agent 可同时访问本地工具和 MCP 工具。
            tools=[*local_tools, *mcp_bundle.tools],
            # 系统提示词决定 Agent 的行为基调与回答边界。
            system_prompt=TRAVEL_SYSTEM_PROMPT,
            # checkpointer 用于同一 thread 下的上下文恢复。
            checkpointer=checkpointer,
            # store 当前没有共享值场景，但接口先保留。
            store=store,
        )

        # 把所有运行时依赖封装成一个容器，方便后续方法统一访问。
        self._runtime = AgentRuntime(
            agent=agent,
            mcp_bundle=mcp_bundle,
            local_tool_names=[tool.name for tool in local_tools],
            checkpointer=checkpointer,
        )

    async def shutdown(self) -> None:
        """关闭运行时关联的 MCP 客户端连接。

        关闭顺序是：
        1. 先尝试关闭 MCP 客户端；
        2. 再关闭 checkpointer 对应的 SQLite 连接；
        3. 最后清空内存中的 runtime 引用。
        """
        # 没启动过时无需做任何清理。
        if self._runtime is None:
            return

        # MCP 客户端不一定一定存在，所以先做空值保护。
        if self._runtime.mcp_bundle.client:
            # 某些客户端的 `close` 可能是同步函数，也可能是异步协程，这里统一兼容。
            close_method = getattr(self._runtime.mcp_bundle.client, "close", None)
            if close_method:
                maybe_result = close_method()
                if hasattr(maybe_result, "__await__"):
                    await maybe_result

        # LangGraph checkpointer 底层持有 SQLite 连接，需要显式关闭。
        await self._runtime.checkpointer.conn.close()
        # 清空 runtime，保证下次会重新初始化。
        self._runtime = None

    def runtime_snapshot(self) -> dict[str, Any]:
        """返回当前运行时状态快照，用于健康检查。

        Returns:
            dict[str, Any]: 包含就绪状态、可用工具列表、MCP 连接情况和错误信息。
        """
        # 未初始化时返回一份“未就绪”的空快照。
        if self._runtime is None:
            return {
                "ready": False,
                "mcp_connected_servers": [],
                "mcp_errors": [],
                "local_tools": [],
                "mcp_tools": [],
            }

        # 已初始化时把运行时关键信息整理成一个稳定结构，供健康检查接口直接返回。
        return {
            "ready": True,
            "mcp_connected_servers": self._runtime.mcp_bundle.connected_servers,
            "mcp_errors": self._runtime.mcp_bundle.errors,
            "local_tools": self._runtime.local_tool_names,
            "mcp_tools": [getattr(tool, "name", "unknown") for tool in self._runtime.mcp_bundle.tools],
        }

    def list_sessions(self, user_id: str) -> list[SessionSummary]:
        """返回会话摘要列表。"""
        return self._chat_store.list_sessions(user_id)

    def get_session_detail(self, user_id: str, thread_id: str) -> SessionDetail | None:
        """返回会话详情。

        Args:
            thread_id: 会话线程 ID。

        Returns:
            SessionDetail | None: 找到则返回详情，否则返回 `None`。
        """
        return self._chat_store.get_session_detail(user_id, thread_id)

    def rename_session(self, user_id: str, thread_id: str, title: str) -> SessionSummary | None:
        """重命名会话。"""
        return self._chat_store.rename_session(user_id, thread_id, title)

    async def delete_session(self, user_id: str, thread_id: str) -> bool:
        """删除会话。

        删除会话时需要同时清理两层数据：
        1. 业务 SQLite 表中的会话与消息；
        2. LangGraph checkpoint 表中的线程状态。
        """
        # 先删业务表；如果业务表里都不存在，就不必再操作 checkpoint。
        deleted = self._chat_store.delete_session(user_id, thread_id)
        # 只有 runtime 已初始化时，才有 checkpointer 可供删除。
        if deleted and self._runtime is not None:
            await self._runtime.checkpointer.adelete_thread(thread_id)
        return deleted

    async def stream_invoke(self, user_id: str, request: ChatInvokeRequest):
        """执行流式聊天并产出 LangGraph 原生流事件。

        在流式前先写入用户消息；在流式结束后写入助手消息，确保会话可重启恢复。
        当前通过 Agent 对象的 `astream(...)` 直接学习 LangGraph 原生事件流。
        """
        # 首次请求时，如果 runtime 还没准备好，就自动完成初始化。
        if self._runtime is None:
            await self.startup()

        # 走到这里时 runtime 一定存在；用断言强调这个前置条件。
        assert self._runtime is not None

        # 先把用户消息落业务表，确保即使后面流式失败，历史里也能看到这一轮提问。
        self._chat_store.append_user_message(user_id, request.thread_id, request.user_message)
        # 找出这条线程当前应该恢复到哪个稳定 checkpoint。
        checkpoint_id = await self._get_effective_checkpoint_id(user_id, request.thread_id)
        # Agent 输入只保留“本轮新增的人类消息”，历史由 checkpoint 恢复。
        model_messages = [HumanMessage(content=request.user_message)]
        # `thread_id` 是 LangGraph 记忆恢复的主键；`checkpoint_id` 用于显式指定恢复起点。
        configurable: dict[str, Any] = {"thread_id": request.thread_id}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        # 这里累计的是流式过程中实时观察到的工具轨迹，便于失败时也能保留调试信息。
        streamed_tool_traces: list[ToolTrace] = []
        # 去重集合用于防止同一个工具调用在 `updates` 里被重复消费。
        seen_called: set[str] = set()
        seen_returned: set[str] = set()
        # `values` 事件通常会携带最终状态快照，后续会从这里恢复完整答案。
        latest_values: dict[str, Any] | None = None
        # `messages` 事件里拿到的是增量 chunk，这里把它累加成完整文本。
        accumulated_chunk: AIMessageChunk | None = None

        try:
            # 直接消费 Agent 的原生流：messages / updates / values。
            async for part in self._runtime.agent.astream(
                {"messages": model_messages},
                config={"configurable": configurable},
                stream_mode=["messages", "updates", "values"],
                version="v2",
            ):
                # 防御式判断：理论上应始终是 dict，但这里避免未来升级导致结构变化时直接崩掉。
                if not isinstance(part, dict):
                    continue

                # `type` 决定这条流事件属于哪一类原生事件。
                part_type = str(part.get("type", "")).strip()
                # `data` 是真正的事件主体。
                raw_data = part.get("data")

                if part_type == "messages":
                    # `messages` 事件里通常是 `(AIMessageChunk, metadata)` 结构。
                    message_chunk, _stream_meta = _extract_ai_chunk_event(raw_data)
                    if message_chunk is None:
                        continue

                    # 第一块 chunk 直接保存，后续 chunk 通过 `+` 运算按 LangChain 规则合并。
                    if accumulated_chunk is None:
                        accumulated_chunk = message_chunk
                    else:
                        accumulated_chunk = accumulated_chunk + message_chunk

                if part_type == "updates":
                    # `updates` 里主要提取工具调用 / 工具返回，供前端实时展示调试轨迹。
                    for _event_name, _event_payload, trace in _extract_tool_events(
                        raw_data, seen_called=seen_called, seen_returned=seen_returned
                    ):
                        streamed_tool_traces.append(trace)
                elif part_type == "values" and isinstance(raw_data, dict):
                    # `values` 是最终状态快照，后续构建最终响应时优先使用。
                    latest_values = raw_data

                # 不对 LangGraph 原生事件做二次语义包装，直接序列化后向外透传。
                yield part_type or "message", _serialize_stream_part(part)
        except BaseException:
            # 无论是前端主动中断、网络断开还是工具异常，都回滚到最近稳定 checkpoint。
            await self.rollback_thread(user_id, request.thread_id)
            # 回滚完成后继续把异常抛出去，交由 API 层转成 SSE error。
            raise

        # 流式正常结束后，把 `values` 和 chunk 累积结果归并成最终助手响应。
        final_response = _build_final_response(
            latest_values=latest_values,
            accumulated_chunk=accumulated_chunk,
            streamed_tool_traces=streamed_tool_traces,
            runtime=self._runtime,
        )

        # 最终只把完整助手消息写入业务表，不存 token 级碎片。
        self._chat_store.append_assistant_message(
            user_id,
            request.thread_id,
            final_response.assistant_message,
            debug=final_response.debug.model_dump(),
        )
        # 这一轮完整成功后，把当前线程最新合法状态标记为新的稳定点。
        await self._mark_thread_stable(user_id, request.thread_id)

    async def rollback_thread(self, user_id: str, thread_id: str) -> None:
        """将线程回滚到最近一个合法的 checkpoint。

        该方法用于处理用户暂停、网络中断或工具回合异常等情况，确保后续仍能继续
        在同一会话里聊天，而不会因为未闭合的 tool call 污染线程状态。
        """
        # runtime 不存在时说明尚未真正执行过 Agent，无需回滚。
        if self._runtime is None:
            return

        # 从 checkpoint 时间线里找出最近一个“工具调用已闭环”的状态。
        stable_checkpoint_id = await self._find_latest_valid_checkpoint_id(thread_id)
        # 同步更新业务表里的稳定 checkpoint 指针。
        self._chat_store.set_stable_checkpoint_id(user_id, thread_id, stable_checkpoint_id)
        # 删除稳定点之后的半成品 checkpoint，避免下轮恢复时再次读到脏状态。
        await self._prune_checkpoints_after(thread_id, stable_checkpoint_id)

    async def _get_effective_checkpoint_id(self, user_id: str, thread_id: str) -> str | None:
        """读取线程当前应该作为下一轮起点的稳定 checkpoint。

        优先使用业务表里已经缓存好的稳定 checkpoint；如果没有，再从 checkpoint
        历史里动态扫描一次，并把结果回写到业务表。
        """
        # 先读业务表缓存，命中时可以避免每轮都扫描 checkpoint 历史。
        stable_checkpoint_id = self._chat_store.get_stable_checkpoint_id(user_id, thread_id)
        if stable_checkpoint_id:
            return stable_checkpoint_id

        # 首次命中不到时，再从 LangGraph checkpoint 历史里推导。
        stable_checkpoint_id = await self._find_latest_valid_checkpoint_id(thread_id)
        if stable_checkpoint_id:
            # 推导成功后顺手缓存，下次就能直接复用。
            self._chat_store.set_stable_checkpoint_id(user_id, thread_id, stable_checkpoint_id)
        return stable_checkpoint_id

    async def _mark_thread_stable(self, user_id: str, thread_id: str) -> None:
        """在一轮成功结束后，记录线程当前最新稳定 checkpoint。"""
        # 成功回合完成后，最新 checkpoint 一定已经是安全可恢复状态。
        stable_checkpoint_id = await self._find_latest_valid_checkpoint_id(thread_id)
        self._chat_store.set_stable_checkpoint_id(user_id, thread_id, stable_checkpoint_id)

    async def _find_latest_valid_checkpoint_id(self, thread_id: str) -> str | None:
        """返回线程最近一个消息链合法的 checkpoint id。

        判定标准是：消息序列中不存在“AI 发出了 tool_calls，但后面没有对应 ToolMessage”
        的半成品状态。
        """
        if self._runtime is None:
            return None

        # `alist` 默认按 checkpoint_id 倒序返回，所以第一个命中的就是最近的稳定点。
        async for item in self._runtime.checkpointer.alist(
            {"configurable": {"thread_id": thread_id}},
            limit=200,
        ):
            # checkpoint 的真实状态存放在 `channel_values.messages` 里。
            messages = item.checkpoint.get("channel_values", {}).get("messages")
            if isinstance(messages, list) and _messages_have_closed_tool_calls(messages):
                return str(item.config["configurable"]["checkpoint_id"])
        return None

    async def _prune_checkpoints_after(self, thread_id: str, checkpoint_id: str | None) -> None:
        """删除稳定点之后的半成品 checkpoint/writes。

        Args:
            thread_id: 需要清理的线程 ID。
            checkpoint_id: 要保留的最后一个稳定 checkpoint；为 `None` 时删除整条线程。
        """
        # 没有 runtime 时说明没有可操作的 checkpointer。
        if self._runtime is None:
            return

        # 这里拿到的是 LangGraph 官方 SQLite checkpointer。
        checkpointer = self._runtime.checkpointer
        # 确保内部表结构已创建完成，避免操作前出现表不存在。
        await checkpointer.setup()

        if checkpoint_id is None:
            # 连稳定点都找不到时，说明整条线程都不可信，直接删掉整条 checkpoint 记录。
            await checkpointer.adelete_thread(thread_id)
            return

        # 下面需要在同一个锁内完成查询和删除，避免并发读写打架。
        async with checkpointer.lock, checkpointer.conn.cursor() as cur:
            # 先找到稳定点之后所有需要删除的 checkpoint。
            await cur.execute(
                """
                SELECT checkpoint_id
                FROM checkpoints
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id > ?
                ORDER BY checkpoint_id ASC
                """,
                (thread_id, checkpoint_id),
            )
            rows = await cur.fetchall()
            ids_to_delete = [str(row[0]) for row in rows]
            if not ids_to_delete:
                # 没有脏 checkpoint 时直接结束。
                return

            placeholders = ",".join("?" for _ in ids_to_delete)
            # `writes` 表保存的是 checkpoint 关联的中间写入，必须先删。
            await cur.execute(
                f"""
                DELETE FROM writes
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id IN ({placeholders})
                """,
                (thread_id, *ids_to_delete),
            )
            # 再删主 checkpoint 记录。
            await cur.execute(
                f"""
                DELETE FROM checkpoints
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id IN ({placeholders})
                """,
                (thread_id, *ids_to_delete),
            )
            # 显式提交事务，让回滚结果立即生效。
            await checkpointer.conn.commit()


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间戳。

    这个函数主要给流式事件或调试信息补统一的 UTC 时间格式。
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _extract_ai_chunk_event(payload: Any) -> tuple[AIMessageChunk | None, dict[str, Any]]:
    """从 LangGraph `messages` 事件中提取 `AIMessageChunk` 与元信息。

    LangGraph 的 `messages` 事件常见形态是：
    - 直接给一个 `AIMessageChunk`
    - 给一个 `(AIMessageChunk, metadata)` 元组
    """
    # 极简场景：payload 本身就是一个 chunk。
    if isinstance(payload, AIMessageChunk):
        return payload, {}

    # 不是 tuple 时，说明不是我们要处理的标准 `messages` 事件结构。
    if not isinstance(payload, tuple):
        return None, {}

    # 下面把 tuple 里的 chunk 和 metadata 拆出来。
    chunk: AIMessageChunk | None = None
    metadata: dict[str, Any] = {}
    for item in payload:
        if isinstance(item, AIMessageChunk) and chunk is None:
            chunk = item
            continue
        if isinstance(item, dict):
            # metadata 可能被拆成多个 dict，统一 merge 到一起。
            metadata.update(item)

    return chunk, metadata


def _extract_chunk_node(metadata: dict[str, Any]) -> str | None:
    """提取 chunk 所在节点名。

    这个辅助函数主要用于调试；LangGraph 不同版本的元信息字段名可能不同，
    所以这里按多个候选 key 依次探测。
    """
    for key in ("langgraph_node", "node", "source"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _messages_have_closed_tool_calls(messages: list[Any]) -> bool:
    """判断消息序列中是否存在未闭合的工具调用。

    Returns:
        bool: `True` 表示消息链合法；`False` 表示存在未闭合的 tool call。
    """
    # 这里保存当前尚未被 ToolMessage 回应的 tool_call_id。
    pending_tool_call_ids: set[str] = set()

    for message in messages:
        if pending_tool_call_ids:
            # 一旦处于等待工具返回阶段，下一条必须是 ToolMessage。
            if not isinstance(message, ToolMessage):
                return False
            tool_call_id = str(message.tool_call_id or "")
            # tool_call_id 对不上，也说明消息链已经损坏。
            if tool_call_id not in pending_tool_call_ids:
                return False
            pending_tool_call_ids.remove(tool_call_id)
            continue

        # 只有 AIMessage 才可能发起工具调用。
        if not isinstance(message, AIMessage):
            continue
        tool_calls = [call for call in message.tool_calls if isinstance(call, dict)]
        if not tool_calls:
            continue
        # 把这条 AIMessage 里声明的所有工具调用都记录为“待返回”。
        pending_tool_call_ids = {str(call.get("id") or "") for call in tool_calls}
        if "" in pending_tool_call_ids:
            # 缺少 tool_call_id 时无法正确配对，直接视为非法状态。
            return False

    # 只有所有 pending id 都被工具返回消化掉，才算真正闭环。
    return not pending_tool_call_ids


def _serialize_stream_part(part: dict[str, Any]) -> dict[str, Any]:
    """将 LangGraph `StreamPart` 递归转换为可 JSON 序列化结构。

    之所以要做这一步，是因为 `BaseMessage`、Pydantic 模型等对象默认不能直接 `json.dumps`。
    """
    return _serialize_native_value(part)


def _serialize_native_value(value: Any) -> Any:
    """递归序列化 LangChain / LangGraph 原生对象。

    处理顺序按照“越特殊的类型越靠前”：
    1. `BaseMessage`
    2. Pydantic `BaseModel`
    3. 容器类型（dict / tuple / list / set）
    4. 其余值原样返回
    """
    if isinstance(value, BaseMessage):
        # LangChain 消息统一转成标准 dict，方便前端识别 `type/data`。
        return message_to_dict(value)
    if isinstance(value, BaseModel):
        # Pydantic 模型直接走 `model_dump`。
        return value.model_dump()
    if isinstance(value, dict):
        # dict 递归序列化每个 value；key 强制转字符串保证 JSON 安全。
        return {str(key): _serialize_native_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        # tuple 转 list，避免 JSON 不支持。
        return [_serialize_native_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_native_value(item) for item in value]
    if isinstance(value, set):
        # set 也统一转 list。
        return [_serialize_native_value(item) for item in value]
    # 标量或原本就可序列化的对象直接返回。
    return value


def _build_final_response(
    *,
    latest_values: dict[str, Any] | None,
    accumulated_chunk: AIMessageChunk | None,
    streamed_tool_traces: list[ToolTrace],
    runtime: AgentRuntime,
) -> ChatInvokeResponse:
    """根据流式过程构建最终响应对象。

    优先级大致是：
    1. 从 `values.messages` 取最终助手文本；
    2. 如果没有，再退回到累积 chunk 文本。
    """
    # `values` 不一定总能拿到 dict，所以先做一次归一化保护。
    values = latest_values if isinstance(latest_values, dict) else {}
    # 从最终状态里抽取完整消息列表。
    messages = _extract_state_messages(values.get("messages"))

    # 如果最终状态里已经有 AIMessage，就优先使用它作为最终文本。
    assistant_from_state = _extract_latest_ai_content(messages).strip()
    # 否则退回到流式 chunk 累积结果。
    assistant_from_chunk = _content_to_text(accumulated_chunk.content).strip() if accumulated_chunk else ""
    assistant_seed = assistant_from_state or assistant_from_chunk

    # 工具轨迹优先从最终状态里重建；拿不到时再退回到流式过程中累积的结果。
    traces_from_state = _extract_tool_traces(messages)
    final_tool_traces = traces_from_state or streamed_tool_traces

    # 如果连普通文本都拿不到，就退回到空字符串，由上游决定如何展示失败占位。
    assistant_message = assistant_seed

    # 最终返回统一的业务响应结构，便于后续写入业务 SQLite 表。
    return ChatInvokeResponse(
        assistant_message=assistant_message,
        debug=ChatDebugInfo(
            tool_traces=final_tool_traces,
            mcp_connected_servers=runtime.mcp_bundle.connected_servers,
            mcp_errors=runtime.mcp_bundle.errors,
        ),
    )


def _extract_state_messages(payload: Any) -> list[BaseMessage]:
    """从 LangGraph values 中抽取消息列表。

    `values.messages` 有时是原生 `BaseMessage` 列表，有时会嵌在更复杂的结构里，
    所以这里做两段式处理。
    """
    if isinstance(payload, list):
        # 最理想的情况：payload 本身就是消息列表。
        return [item for item in payload if isinstance(item, BaseMessage)]
    # 否则递归遍历整棵结构树，把里面所有 `BaseMessage` 抽出来。
    return list(_iter_base_messages(payload))


def _extract_tool_events(
    payload: Any,
    *,
    seen_called: set[str],
    seen_returned: set[str],
):
    """从 LangGraph `updates` 中提取工具调用/返回事件并去重。

    `updates` 里可能同时出现模型节点和工具节点的消息，这里统一解析成
    `ToolTrace`，供调试信息和前端工具时间线使用。
    """
    for message in _iter_base_messages(payload):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if not isinstance(call, dict):
                    continue
                # 缺少 call_id 时，用工具名 + 参数生成一个稳定键用于去重。
                tool_name = str(call.get("name", "unknown"))
                args = call.get("args", {})
                call_id = str(call.get("id") or _stable_call_key(tool_name, args))
                if call_id in seen_called:
                    continue
                seen_called.add(call_id)
                # 这里同时返回事件名、轻量 payload 和结构化 trace，兼顾不同消费方。
                trace = ToolTrace(phase="called", tool_name=tool_name, payload=args)
                yield "tool_called", {"tool_name": tool_name, "payload": args}, trace
            continue

        if not isinstance(message, ToolMessage):
            continue

        # ToolMessage 代表工具已经真正执行完成。
        tool_name = str(message.name or "unknown")
        payload_text = _content_to_text(message.content)
        returned_key = str(message.tool_call_id or f"{tool_name}:{payload_text}")
        if returned_key in seen_returned:
            continue
        seen_returned.add(returned_key)

        trace = ToolTrace(phase="returned", tool_name=tool_name, payload=payload_text)
        yield (
            "tool_returned",
            {"tool_name": tool_name, "payload": payload_text},
            trace,
        )


def _iter_base_messages(payload: Any):
    """递归遍历负载中的 LangChain `BaseMessage`。

    这个生成器是很多辅助函数的基础能力：只要给它一个复杂嵌套结构，
    它就能把里面所有 LangChain 消息对象挖出来。
    """
    if isinstance(payload, BaseMessage):
        # 命中消息对象时直接产出。
        yield payload
        return

    if isinstance(payload, dict):
        # dict 场景下递归扫描所有 value。
        for value in payload.values():
            if isinstance(value, (dict, list, tuple, set, BaseMessage)):
                yield from _iter_base_messages(value)
        return

    if isinstance(payload, (list, tuple, set)):
        # 序列容器场景下递归扫描每个元素。
        for item in payload:
            if isinstance(item, (dict, list, tuple, set, BaseMessage)):
                yield from _iter_base_messages(item)


def _stable_call_key(tool_name: str, args: Any) -> str:
    """为缺失 call_id 的工具调用生成稳定去重键。

    某些兼容模型或中间层可能不给 `tool_call_id`，这时只能退化到
    “工具名 + 参数” 级别做去重。
    """
    try:
        # 优先按 JSON 排序序列化，保证同样参数顺序不同也能得到同一键。
        args_repr = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        # 遇到不可 JSON 序列化的值时，退回到字符串表示。
        args_repr = str(args)
    return f"{tool_name}:{args_repr}"


def _extract_latest_ai_content(messages: list[BaseMessage]) -> str:
    """从消息列表中提取最新一条 `AIMessage` 文本。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _content_to_text(message.content)
    return ""


def _extract_tool_traces(messages: list[BaseMessage]) -> list[ToolTrace]:
    """从消息列表中重建工具调用轨迹。

    这个方法主要用于从最终状态快照里回放出完整工具时间线。
    """
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
            # 工具返回统一记录成 `returned` 轨迹。
            traces.append(
                ToolTrace(
                    phase="returned",
                    tool_name=str(message.name or "unknown"),
                    payload=_content_to_text(message.content),
                )
            )

    return traces


def _content_to_text(content: Any) -> str:
    """将消息 content 统一归一化为字符串。

    LangChain 的 content 既可能是纯字符串，也可能是 content block 列表，
    这里统一处理成便于展示和持久化的文本。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # content block 列表场景下，尽量只提取 text 类型块。
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            else:
                # 兜底情况下保留原始字符串表示，避免信息丢失。
                chunks.append(str(item))
        return "\n".join(chunks).strip()
    if content is None:
        return ""
    return str(content)
