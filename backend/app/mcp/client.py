"""MCP 客户端装配逻辑（langchain.mcp MCPAdapter + fastmcp ClientGroup）。

迁移说明（langchain-mcp-adapters → langchain.mcp，2026-09）：
- `MultiServerMCPClient` 被 `langchain.mcp.MCPAdapter` 取代；transport 由
  fastmcp 按 MCPConfig 条目推断（command/args → stdio，url → streamable HTTP，
  显式 `"transport": "sse"` 仅用于旧版 SSE 服务器）。
- 每个服务器包一层单成员 `ClientGroup`：一是保留旧的 `{server}_{tool}` 命名
  前缀（前端工具显示名与健康检查依赖），二是维持按服务器隔离的错误边界。
- 发现（list_tools）在 adapter 上下文内完成后即可退出上下文：返回的工具持有
  各自的客户端，每次调用自开会话，无需在 shutdown 时统一关闭连接。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastmcp.client.group import ClientGroup
from langchain.mcp import MCPAdapter

logger = logging.getLogger(__name__)

_ENTRY_KEYS = {"url", "command", "args", "env", "headers", "mode"}


@dataclass
class MCPToolBundle:
    """MCP 工具加载结果。

    Attributes:
        tools: 可供 Agent 调用的工具列表（名字带 `{server}_` 前缀）。
        connected_servers: 成功连接的 MCP 服务名列表。
        errors: 加载错误列表（字符串形式）。
    """

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _normalize_entry(connection: dict[str, Any]) -> dict[str, Any]:
    """把内部连接配置转换为 fastmcp `MCPConfig` 条目。

    - streamable_http 由 url 推断，不再显式写 transport；sse 是协议废弃但
      fastmcp 仍支持的旧传输，显式传递。
    - fastmcp 4 引入协议"时代"协商：现有 MCP 服务器都建于 legacy 时代
      （旧 adapters 只支持 legacy），默认固定 `mode="legacy"` 保持行为不变；
      新时代服务器可在配置中显式覆盖 `mode`。
    """
    entry = {key: value for key, value in connection.items() if key in _ENTRY_KEYS}
    if connection.get("transport") == "sse":
        entry["transport"] = "sse"
    entry.setdefault("mode", "legacy")
    return entry


async def load_mcp_tools(connections: dict[str, dict[str, Any]]) -> MCPToolBundle:
    """基于连接配置初始化 MCP 工具集合。

    Args:
        connections: 已校验的 MCP 连接配置。

    Returns:
        MCPToolBundle: 包含工具、连接状态与错误信息；单个服务器失败不影响其他。
    """
    if not connections:
        return MCPToolBundle()

    tools: list[Any] = []
    connected_servers: list[str] = []
    errors: list[str] = []

    for server_name, connection in connections.items():
        try:
            group = ClientGroup.from_config(
                {"mcpServers": {server_name: _normalize_entry(connection)}}
            )
            adapter = MCPAdapter(group)
            async with adapter:
                loaded_tools = await adapter.list_tools()
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.exception("Failed to initialize MCP server %s", server_name)
            errors.append(f"{server_name}: {exc}")
            continue

        tools.extend(loaded_tools)
        connected_servers.append(server_name)

    return MCPToolBundle(
        tools=tools,
        connected_servers=connected_servers,
        errors=errors,
    )
