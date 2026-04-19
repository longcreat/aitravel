"""公开语音播放 API。"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent.service import TravelAgentService
from app.api.deps import get_agent_service

router = APIRouter(prefix="/api/speech", tags=["speech"])


@router.get("/play/{token}")
async def play_speech(
    token: str,
    service: TravelAgentService = Depends(get_agent_service),
) -> StreamingResponse:
    """根据短时 token 返回可直接播放的音频流。"""
    try:
        target = service.get_speech_playback_target(token)
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid speech playback token") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return StreamingResponse(
        target.iterator,
        media_type=target.media_type,
        headers={"Cache-Control": "no-cache"},
    )
