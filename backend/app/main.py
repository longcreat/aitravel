"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.deps import get_agent_service
from app.db.bootstrap import bootstrap_sqlite_database
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """管理应用生命周期：启动时初始化 Agent，关闭时释放资源。"""
    await get_agent_service().startup()
    yield
    await get_agent_service().shutdown()


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例并注册路由与生命周期事件。"""
    bootstrap_sqlite_database()
    app = FastAPI(title="AI Travel Agent API", version="0.1.0", lifespan=lifespan)

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

    return app
