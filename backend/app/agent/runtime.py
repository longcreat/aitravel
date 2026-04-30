"""Agent 运行时装配与生命周期管理。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent

from app.agent.context import AgentRequestContext
from app.agent.middleware import build_agent_middleware
from app.llm.provider import build_chat_model
from app.mcp.client import MCPToolBundle, load_mcp_tools
from app.mcp.config import load_mcp_connections
from app.tool.local_tools import get_local_tools


def build_memory_runtime(sqlite_db_path: Path):
    """惰性导入 memory runtime，避免模块加载阶段触发重依赖。"""
    from app.memory.runtime import build_memory_runtime as _build_memory_runtime

    return _build_memory_runtime(sqlite_db_path)


@dataclass
class AgentRuntime:
    """Agent 运行时容器。"""

    agent: Any
    mcp_bundle: MCPToolBundle
    local_tool_names: list[str]
    checkpointer: Any


class AgentRuntimeService:
    """管理 Agent 运行时的装配、关闭与状态快照。"""

    def __init__(self, mcp_config_path: Path, sqlite_db_path: Path) -> None:
        self._mcp_config_path = mcp_config_path
        self._sqlite_db_path = sqlite_db_path
        self._runtime: AgentRuntime | None = None

    @property
    def runtime(self) -> AgentRuntime | None:
        """返回当前运行时；未初始化时为 `None`。"""
        return self._runtime

    def require_runtime(self) -> AgentRuntime:
        """返回当前运行时；未初始化时抛出异常。"""
        if self._runtime is None:
            raise RuntimeError("Agent runtime is not initialized")
        return self._runtime

    async def startup(self) -> None:
        """初始化 Agent 运行时。"""
        if self._runtime is not None:
            return

        local_tools = get_local_tools()
        connections = load_mcp_connections(self._mcp_config_path)
        mcp_bundle = await load_mcp_tools(connections)

        checkpointer, store = await build_memory_runtime(self._sqlite_db_path)
        model = build_chat_model()
        agent = create_agent(
            model=model,
            tools=[*local_tools, *mcp_bundle.tools],
            context_schema=AgentRequestContext,
            middleware=build_agent_middleware(),
            checkpointer=checkpointer,
            store=store,
        )

        self._runtime = AgentRuntime(
            agent=agent,
            mcp_bundle=mcp_bundle,
            local_tool_names=[tool.name for tool in local_tools],
            checkpointer=checkpointer,
        )

    async def shutdown(self) -> None:
        """关闭 MCP 客户端与 SQLite checkpointer。"""
        if self._runtime is None:
            return

        clients = self._runtime.mcp_bundle.clients or (
            [self._runtime.mcp_bundle.client] if self._runtime.mcp_bundle.client else []
        )
        seen_client_ids: set[int] = set()
        for client in clients:
            if client is None or id(client) in seen_client_ids:
                continue
            seen_client_ids.add(id(client))
            close_method = getattr(client, "close", None)
            if close_method:
                maybe_result = close_method()
                if hasattr(maybe_result, "__await__"):
                    await maybe_result

        await self._runtime.checkpointer.conn.close()
        self._runtime = None

    def snapshot(self) -> dict[str, Any]:
        """返回当前运行时快照，用于健康检查。"""
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
