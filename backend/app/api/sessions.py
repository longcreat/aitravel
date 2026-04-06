"""会话管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agent.service import TravelAgentService
from app.api.deps import get_agent_service
from app.schemas.chat import RenameSessionRequest, SessionDetail, SessionSummary

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
async def list_sessions(service: TravelAgentService = Depends(get_agent_service)) -> list[SessionSummary]:
    """返回会话摘要列表（按最近活跃时间倒序）。"""
    return service.list_sessions()


@router.get("/{thread_id}", response_model=SessionDetail)
async def get_session(thread_id: str, service: TravelAgentService = Depends(get_agent_service)) -> SessionDetail:
    """返回指定会话详情。"""
    detail = service.get_session_detail(thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/{thread_id}", response_model=SessionSummary)
async def rename_session(
    thread_id: str,
    payload: RenameSessionRequest,
    service: TravelAgentService = Depends(get_agent_service),
) -> SessionSummary:
    """重命名会话。"""
    summary = service.rename_session(thread_id, payload.title)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found or invalid title")
    return summary


@router.delete("/{thread_id}")
async def delete_session(thread_id: str, service: TravelAgentService = Depends(get_agent_service)) -> dict:
    """删除会话及其全部消息。"""
    deleted = await service.delete_session(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}
