"""FastAPI 依赖注入定义。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.agent.service import TravelAgentService


@lru_cache
def get_agent_service() -> TravelAgentService:
    """返回全局单例 `TravelAgentService`。

    使用 `lru_cache` 让同一进程内始终复用同一个服务实例，
    以共享 Agent 运行时与 MCP 连接状态。
    """
    backend_root = Path(__file__).resolve().parents[2]
    config_path = backend_root / "config" / "mcp.servers.json"
    sqlite_path = Path(os.getenv("CHAT_SQLITE_PATH", str(backend_root / "data" / "chat.db")))
    return TravelAgentService(mcp_config_path=config_path, sqlite_db_path=sqlite_path)
