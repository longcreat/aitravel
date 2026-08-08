"""实时语音识别（按住说话）WebSocket API。

协议：
- 前端 → 后端：二进制 PCM 帧（16kHz 16bit 单声道）
- 前端 → 后端：`{"action": "finish"}` 结束识别
- 后端 → 前端：`{"type": "sentence", "text", "sentence_end"}`（实时/最终句）
- 后端 → 前端：`{"type": "done", "text"}`（完整结果）
- 后端 → 前端：`{"type": "error", "message"}`
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_auth_service
from app.auth.service import AuthService
from app.speech.stt import DashScopeSttSession, stt_api_key, stt_model

router = APIRouter(prefix="/api/stt", tags=["stt"])
logger = logging.getLogger(__name__)


async def _forward_events(websocket: WebSocket, session: DashScopeSttSession) -> None:
    """把 SDK 事件队列转发给前端；收到 closed 或断连时退出。"""
    try:
        while True:
            event = await session.events()
            if event["type"] == "closed":
                return
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:  # pragma: no cover - 前端中途断连
        return


@router.websocket("/ws")
async def stt_websocket(
    websocket: WebSocket,
    token: str = "",
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    """实时语音识别：token（JWT）经 query 传入，校验后双向转发音频与结果。"""
    try:
        auth_service.get_current_user(token)
    except Exception:  # noqa: BLE001 - 未认证/无效 token
        await websocket.close(code=4401)
        return

    if not stt_api_key():
        await websocket.close(code=4403)
        return

    await websocket.accept()

    session = DashScopeSttSession(api_key=stt_api_key(), model=stt_model())
    session.start()
    if not session.ready:
        await websocket.close(code=4402)
        return

    forward_task: asyncio.Task[None] | None = None
    try:
        forward_task = asyncio.create_task(_forward_events(websocket, session))
        while True:
            message: dict[str, Any] = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("type") == "websocket.receive":
                text = message.get("text")
                if text is not None:
                    try:
                        data = json.loads(text)
                    except ValueError:
                        continue
                    if data.get("action") == "finish":
                        break
                else:
                    audio = message.get("bytes")
                    if audio:
                        session.send_audio_frame(audio)
    except WebSocketDisconnect:  # pragma: no cover - 由 receive 抛出的断连
        pass
    finally:
        await asyncio.to_thread(session.finish)
        if forward_task is not None:
            forward_task.cancel()
            try:
                await forward_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await websocket.close()
        except Exception:
            pass
