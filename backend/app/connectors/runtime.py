"""按用户拼装 MCP connector 工具集的运行时辅助。

重建（2026-10）：走 `app.mcp.client.assemble_mcp_tools` 统一装配管线——
- 用户 token 作为 fastmcp 原生 `auth` 凭证挂在 client 上（官方 per-user
  authentication 模式），不再烘焙进静态 headers；
- 多 connector 并行发现，单个失败不阻塞；
- connector 注册表可为每个 connector 配置协议时代（`protocol_mode`，
  默认 legacy）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.connectors.service import ConnectorService
from app.mcp.client import MCPToolBundle, ServerSpec, assemble_mcp_tools

logger = logging.getLogger(__name__)


@dataclass
class UserConnectorTools(MCPToolBundle):
    """单次聊天会话期间的用户级 MCP 工具集合。

    工具持有各自客户端、按调用自开会话，无需显式释放连接。
    """

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # 参与 agent 构建缓存的签名：connector 集合 + 凭证版本
    signature: str = ""


@asynccontextmanager
async def user_connector_tools(connector_service: ConnectorService, user_id: str):
    """上下文管理器：返回该用户已连接 connector 的 MCP 工具集合。"""
    bundle = UserConnectorTools()
    active = await connector_service.list_user_active_connections(user_id)
    if not active:
        yield bundle
        return

    specs: list[ServerSpec] = []
    connector_ids: list[str] = []
    for definition, _row, access_token in active:
        mode = getattr(definition, "protocol_mode", None) or "legacy"
        specs.append(
            ServerSpec(
                name=definition.id,
                url=definition.mcp_server_url,
                auth=access_token,
                mode=mode,
            )
        )
        connector_ids.append(definition.id)

    result = await assemble_mcp_tools(specs)
    bundle.tools = result.tools
    bundle.connected_servers = result.connected_servers
    bundle.errors = result.errors
    # 签名：谁的工具集 + 凭证当前版本（token 刷新后版本变化 → 缓存失效）
    bundle.signature = f"{connector_service.credentials_version()}:{','.join(sorted(connector_ids))}"

    yield bundle
