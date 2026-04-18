"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.deps import get_agent_service
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router


def _load_env_file() -> None:
    """从 `backend/.env` 读取环境变量并写入当前进程。

    约定：
    - 已存在于进程环境的变量优先级更高，不会被覆盖；
    - 仅解析 `KEY=VALUE` 形式的行，忽略注释与空行。
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例并注册路由与生命周期事件。"""
    _load_env_file()
    app = FastAPI(title="AI Travel Agent API", version="0.1.0")

    allow_origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allow_origins if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(sessions_router)

    @app.on_event("startup")
    async def _startup() -> None:
        """应用启动时初始化 Agent 运行时。"""
        await get_agent_service().startup()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        """应用关闭时释放 Agent 外部资源连接。"""
        await get_agent_service().shutdown()

    return app


app = create_app()
