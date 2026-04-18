"""FastAPI 依赖注入定义。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.agent.service import TravelAgentService
from app.auth.service import AuthService
from app.db.bootstrap import bootstrap_sqlite_database
from app.schemas.auth import AuthUser


@lru_cache
def get_agent_service() -> TravelAgentService:
    """返回全局单例 `TravelAgentService`。

    使用 `lru_cache` 让同一进程内始终复用同一个服务实例，
    以共享 Agent 运行时与 MCP 连接状态。
    """
    backend_root = Path(__file__).resolve().parents[2]
    config_path = backend_root / "config" / "mcp.servers.json"
    sqlite_path = bootstrap_sqlite_database()
    return TravelAgentService(mcp_config_path=config_path, sqlite_db_path=sqlite_path)


@lru_cache
def get_auth_service() -> AuthService:
    """返回全局单例 `AuthService`。"""
    sqlite_path = bootstrap_sqlite_database()
    return AuthService(sqlite_db_path=sqlite_path)


_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUser:
    """解析 Bearer Token 并返回当前用户。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return auth_service.get_current_user(credentials.credentials)
