"""用户级 MCP connector 领域模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ConnectorAuthStatus = Literal["pending", "connected", "expired", "revoked", "failed"]


class ConnectorDefinition(BaseModel):
    """管理员维护的 connector 元数据（不含敏感凭证）。"""

    id: str
    display_name: str
    description: str = ""
    icon_url: str | None = None
    mcp_server_url: str
    default_scopes: str | None = None
    enabled: bool = True


class ConnectorState(BaseModel):
    """单个 connector 在当前用户视角下的状态。"""

    id: str
    display_name: str
    description: str = ""
    icon_url: str | None = None
    mcp_server_url: str
    enabled: bool = True
    status: ConnectorAuthStatus | Literal["disconnected"] = "disconnected"
    connected_at: str | None = None
    last_error: str | None = None


class ListConnectorsResponse(BaseModel):
    """`GET /api/connectors` 响应。"""

    connectors: list[ConnectorState] = Field(default_factory=list)


class StartAuthorizationResponse(BaseModel):
    """`POST /api/connectors/{id}/authorize` 响应。"""

    authorize_url: str
    state: str
    expires_in: int
