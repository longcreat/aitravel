"""会话管理 API。"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.agent.service import TravelAgentService
from app.api.deps import get_agent_service, get_current_user
from app.schemas.auth import AuthUser
from app.schemas.chat import (
    PersistedChatMessage,
    RenameSessionRequest,
    SessionDetail,
    SessionModelProfileState,
    SessionSummary,
    SpeechPlaybackUrlResponse,
    StreamErrorPayload,
    SwitchAssistantVersionRequest,
    UpdateAssistantFeedbackRequest,
    UpdateSessionModelProfileRequest,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
GENERIC_STREAM_ERROR_MESSAGE = "请求失败，请稍后重试。"


def _encode_sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> list[SessionSummary]:
    """返回会话摘要列表（按最近活跃时间倒序）。"""
    return service.list_sessions(current_user.id)


@router.get("/{thread_id}", response_model=SessionDetail)
async def get_session(
    thread_id: str,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> SessionDetail:
    """返回指定会话详情。"""
    detail = service.get_session_detail(current_user.id, thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/{thread_id}", response_model=SessionSummary)
async def rename_session(
    thread_id: str,
    payload: RenameSessionRequest,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> SessionSummary:
    """重命名会话。"""
    summary = service.rename_session(current_user.id, thread_id, payload.title)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found or invalid title")
    return summary


@router.patch("/{thread_id}/model-profile", response_model=SessionModelProfileState)
async def update_session_model_profile(
    thread_id: str,
    payload: UpdateSessionModelProfileRequest,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> SessionModelProfileState:
    """更新线程当前模型档位。"""
    try:
        state = service.update_session_model_profile(current_user.id, thread_id, payload.model_profile_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return state


@router.delete("/{thread_id}")
async def delete_session(
    thread_id: str,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> dict:
    """删除会话及其全部消息。"""
    deleted = await service.delete_session(current_user.id, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/{thread_id}/messages/{message_id}/regenerate/stream")
async def regenerate_message(
    thread_id: str,
    message_id: str,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    """重新生成最新一条 assistant 回复。"""

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async for event_name, event_payload in service.stream_regenerate(current_user.id, thread_id, message_id):
                yield _encode_sse(event_name, event_payload)
        except asyncio.CancelledError:  # pragma: no cover
            return
        except ValueError as exc:
            yield _encode_sse("error", StreamErrorPayload(message=str(exc)).model_dump())
        except Exception:  # pragma: no cover
            yield _encode_sse("error", StreamErrorPayload(message=GENERIC_STREAM_ERROR_MESSAGE).model_dump())

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/{thread_id}/messages/{message_id}/current-version", response_model=PersistedChatMessage)
async def switch_message_version(
    thread_id: str,
    message_id: str,
    payload: SwitchAssistantVersionRequest,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> PersistedChatMessage:
    """切换 assistant 当前展示版本。"""
    message = service.switch_assistant_version(current_user.id, thread_id, message_id, payload.version_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Assistant message or version not found")
    return message


@router.patch(
    "/{thread_id}/messages/{message_id}/versions/{version_id}/feedback",
    response_model=PersistedChatMessage,
)
async def update_message_feedback(
    thread_id: str,
    message_id: str,
    version_id: str,
    payload: UpdateAssistantFeedbackRequest,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> PersistedChatMessage:
    """更新 assistant version 点赞/点踩。"""
    message = service.update_assistant_feedback(
        current_user.id, thread_id, message_id, version_id, payload.feedback
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Assistant version not found")
    return message


@router.get(
    "/{thread_id}/messages/{message_id}/versions/{version_id}/speech/playback-url",
    response_model=SpeechPlaybackUrlResponse,
)
async def get_message_speech_playback_url(
    thread_id: str,
    message_id: str,
    version_id: str,
    request: Request,
    service: TravelAgentService = Depends(get_agent_service),
    current_user: AuthUser = Depends(get_current_user),
) -> SpeechPlaybackUrlResponse:
    """返回 assistant version 的语音播放地址。"""
    try:
        playback_url, speech_status = service.get_speech_playback_url(
            current_user.id,
            thread_id,
            message_id,
            version_id,
            base_url=str(request.base_url).rstrip("/"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return SpeechPlaybackUrlResponse(playback_url=playback_url, speech_status=speech_status)
