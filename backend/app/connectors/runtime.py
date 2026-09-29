"""按用户拼装 MCP 工具集的运行时辅助。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastmcp.client.group import ClientGroup
from langchain.mcp import MCPAdapter

from app.connectors.service import ConnectorService

logger = logging.getLogger(__name__)


@dataclass
class UserConnectorTools:
    """单次聊天会话期间的用户级 MCP 工具集合。

    工具持有各自客户端、按调用自开会话，无需显式释放连接。
    """

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _is_sse_url(mcp_server_url: str) -> bool:
    """SSE 是协议废弃传输，仅对以 /sse 结尾的旧服务器显式声明。"""
    return urlparse(mcp_server_url).path.lower().endswith("/sse")


@asynccontextmanager
async def user_connector_tools(connector_service: ConnectorService, user_id: str):
    """上下文管理器：返回该用户已连接 connector 的 MCP 工具集合。"""
    bundle = UserConnectorTools()
    active = await connector_service.list_user_active_connections(user_id)
    for definition, _row, access_token in active:
        entry: dict[str, Any] = {
            "url": definition.mcp_server_url,
            "headers": {"Authorization": f"Bearer {access_token}"},
            # 现有 connector 服务器建于 legacy 协议时代（见 app/mcp/client.py 说明）
            "mode": "legacy",
        }
        if _is_sse_url(definition.mcp_server_url):
            entry["transport"] = "sse"
        try:
            group = ClientGroup.from_config({"mcpServers": {definition.id: entry}})
            adapter = MCPAdapter(group)
            async with adapter:
                tools = await adapter.list_tools()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to load tools for connector=%s user=%s: %s",
                definition.id,
                user_id,
                exc,
            )
            bundle.errors.append(f"{definition.id}: {exc}")
            continue
        bundle.tools.extend(tools)
        bundle.connected_servers.append(definition.id)

    yield bundle
