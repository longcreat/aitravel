"""MCP 客户端装配逻辑。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


@dataclass
class MCPToolBundle:
    """MCP 工具加载结果。

    Attributes:
        tools: 可供 Agent 调用的工具列表。
        connected_servers: 成功连接的 MCP 服务名列表。
        errors: 加载错误列表（字符串形式）。
        client: MCP 客户端实例（用于后续关闭连接）。
    """

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    client: MultiServerMCPClient | None = None
    clients: list[MultiServerMCPClient] = field(default_factory=list)


async def load_mcp_tools(connections: dict[str, dict[str, Any]]) -> MCPToolBundle:
    """基于连接配置初始化 MCP 工具集合。

    Args:
        connections: 已校验的 MCP 连接配置。

    Returns:
        MCPToolBundle: 包含工具、连接状态与错误信息。
    """
    if not connections:
        return MCPToolBundle()

    tools: list[Any] = []
    connected_servers: list[str] = []
    errors: list[str] = []
    clients: list[MultiServerMCPClient] = []

    for server_name, connection in connections.items():
        client = MultiServerMCPClient(connections={server_name: connection}, tool_name_prefix=True)
        clients.append(client)
        try:
            loaded_tools = await client.get_tools()
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
        client=clients[0] if clients else None,
        clients=clients,
    )
