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


async def load_mcp_tools(connections: dict[str, dict[str, Any]]) -> MCPToolBundle:
    """基于连接配置初始化 MCP 工具集合。

    Args:
        connections: 已校验的 MCP 连接配置。

    Returns:
        MCPToolBundle: 包含工具、连接状态与错误信息。
    """
    if not connections:
        return MCPToolBundle()

    client = MultiServerMCPClient(connections=connections, tool_name_prefix=True)
    try:
        tools = await client.get_tools()
        return MCPToolBundle(
            tools=list(tools),
            connected_servers=list(connections.keys()),
            errors=[],
            client=client,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback path
        logger.exception("Failed to initialize MCP connections")
        return MCPToolBundle(
            tools=[],
            connected_servers=[],
            errors=[str(exc)],
            client=client,
        )
