"""健康检查 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agent.service import TravelAgentService
from app.api.deps import get_agent_service

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(service: TravelAgentService = Depends(get_agent_service)) -> dict:
    """返回服务健康状态与 Agent 运行时快照。"""
    snapshot = service.runtime_snapshot()
    return {"status": "ok", **snapshot}
