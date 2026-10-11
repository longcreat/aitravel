"""实时语音识别 WebSocket API 测试（不触网，SDK 用 fake 替换）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import deps
from app.main import create_app


class _NoopAgentService:
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def runtime_snapshot(self) -> dict:
        return {"ready": False, "mcp_connected_servers": [], "mcp_errors": [], "local_tools": [], "mcp_tools": []}


class _FakeOmniConversation:
    """按真实 OmniRealtimeConversation 接口的最小 fake。

    connect 同步回调 on_open；commit 回放一次最终识别结果；close 回调 on_close。
    """

    instances: list["_FakeOmniConversation"] = []

    def __init__(self, model: str, callback, **kwargs) -> None:
        self.model = model
        self.callback = callback
        self.kwargs = kwargs
        self.audio_frames: list[str] = []
        self.committed = False
        self.closed = False
        _FakeOmniConversation.instances.append(self)

    def connect(self) -> None:
        self.callback.on_open()

    def update_session(self, **kwargs) -> None:
        self.session_kwargs = kwargs

    def append_audio(self, audio_b64: str) -> None:
        self.audio_frames.append(audio_b64)

    def commit(self) -> None:
        self.committed = True
        self.callback.on_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "我想去北京",
            }
        )

    def end_session_async(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
        self.callback.on_close()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-stt-ws-0123456789")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "demo")
    monkeypatch.setenv("SMTP_PASSWORD", "demo")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.setattr("app.main.get_agent_service", lambda: _NoopAgentService())
    monkeypatch.setattr("app.auth.service.secrets.randbelow", lambda _limit: 123456)
    monkeypatch.setattr("app.auth.service.AuthService._send_email", lambda self, **_kwargs: None)
    monkeypatch.setenv("ALIYUN_STT_API_KEY", "test-stt-key")

    _FakeOmniConversation.instances.clear()
    monkeypatch.setattr("app.speech.stt.OmniRealtimeConversation", _FakeOmniConversation)

    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()


def _register_and_login(client: TestClient) -> str:
    send = client.post("/api/auth/send-code", json={"email": "stt@example.com", "purpose": "register"})
    assert send.status_code == 200
    verify = client.post(
        "/api/auth/verify-code",
        json={"email": "stt@example.com", "code": "123456", "purpose": "register"},
    )
    assert verify.status_code == 200
    return verify.json()["access_token"]


def test_stt_ws_rejects_missing_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/stt/ws"):
            pass
    assert exc_info.value.code == 4401


def test_stt_ws_rejects_invalid_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/stt/ws?token=garbage"):
            pass
    assert exc_info.value.code == 4401


def test_stt_ws_requires_api_key(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.delenv("ALIYUN_STT_API_KEY", raising=False)
    monkeypatch.delenv("ALIYUN_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    token = _register_and_login(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/stt/ws?token={token}"):
            pass
    assert exc_info.value.code == 4403


def test_stt_ws_full_flow(client: TestClient) -> None:
    token = _register_and_login(client)
    audio = b"\x00\x01\x02\x03" * 100

    with client.websocket_connect(f"/api/stt/ws?token={token}") as websocket:
        assert websocket.receive_json() == {"type": "ready"}

        websocket.send_bytes(audio)
        time.sleep(0.05)
        import base64

        assert base64.b64decode(_FakeOmniConversation.instances[0].audio_frames[0]) == audio

        websocket.send_text(json.dumps({"action": "finish"}))

        sentence = websocket.receive_json()
        done = websocket.receive_json()
        assert sentence == {"type": "sentence", "text": "我想去北京", "sentence_end": True}
        assert done == {"type": "done", "text": "我想去北京"}

        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert _FakeOmniConversation.instances[0].committed is True
    assert _FakeOmniConversation.instances[0].closed is True
