"""按用户拼装 MCP 工具集的运行时辅助。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.connectors.service import ConnectorService

logger = logging.getLogger(__name__)


@dataclass
class UserConnectorTools:
    """单次聊天会话期间的用户级 MCP 工具集合。"""

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _clients: list[MultiServerMCPClient] = field(default_factory=list)

    async def aclose(self) -> None:
        """释放底层 MCP 客户端连接。"""
        for client in self._clients:
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                logger.exception("Failed to close per-user MCP client")


def _infer_transport(mcp_server_url: str) -> str:
    """根据 URL 推断 langchain-mcp-adapters 用的 transport。"""
    parsed = urlparse(mcp_server_url)
    path = parsed.path.lower()
    if path.endswith("/sse"):
        return "sse"
    return "streamable_http"


@asynccontextmanager
async def user_connector_tools(connector_service: ConnectorService, user_id: str):
    """上下文管理器：返回该用户已连接 connector 的 MCP 工具集合。

    用 `async with` 管理生命周期，退出时自动关闭 MCP client。
    """
    bundle = UserConnectorTools()
    try:
        active = await connector_service.list_user_active_connections(user_id)
        for definition, _row, access_token in active:
            transport = _infer_transport(definition.mcp_server_url)
            connection_payload = {
                "transport": transport,
                "url": definition.mcp_server_url,
                "headers": {"Authorization": f"Bearer {access_token}"},
            }
            client = MultiServerMCPClient(
                connections={definition.id: connection_payload},
                tool_name_prefix=True,
            )
            try:
                tools = await client.get_tools()
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
            bundle._clients.append(client)

        yield bundle
    finally:
        await bundle.aclose()
