"""聊天流式 API。

本模块以最薄的一层 SSE 传输 LangGraph 原生流事件，便于学习其
`messages / updates / values` 事件结构。
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.service import TravelAgentService
from app.api.deps import get_agent_service
from app.schemas.chat import ChatInvokeRequest, StreamErrorPayload

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _encode_sse(event: str, data: dict) -> bytes:
    """将事件编码为 SSE 协议文本块。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


@router.post("/stream")
async def stream_chat(
    payload: ChatInvokeRequest,
    service: TravelAgentService = Depends(get_agent_service),
) -> StreamingResponse:
    """以 SSE 方式返回 LangGraph 原生流事件。"""

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async for event_name, event_payload in service.stream_invoke(payload):
                yield _encode_sse(event_name, event_payload)
        except asyncio.CancelledError:  # pragma: no cover - 由客户端中断触发
            return
        except Exception as exc:  # pragma: no cover - defensive boundary
            yield _encode_sse(
                "error",
                StreamErrorPayload(message=f"Agent stream failed: {exc}").model_dump(),
            )

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
