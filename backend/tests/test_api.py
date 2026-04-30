from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_agent_service, get_current_user
from app.main import create_app
from app.schemas.auth import AuthUser
from app.schemas.chat import (
    AssistantVersion,
    ChatMetaInfo,
    ChatModelProfile,
    PersistedChatMessage,
    SessionDetail,
    SessionModelProfileState,
    SessionSummary,
)
from app.speech.service import SpeechPlaybackTarget


async def _fake_audio_stream():
    yield b"fake-mp3-bytes"


def _user_message_payload(message_id: str, text: str) -> dict:
    return {
        "id": message_id,
        "role": "user",
        "text": text,
        "parts": [{"id": f"{message_id}-text", "type": "text", "text": text, "status": "completed"}],
        "status": "completed",
        "meta": None,
        "current_version_id": None,
        "versions": [],
        "can_regenerate": False,
        "created_at": "2026-04-05T00:00:00Z",
    }


def _assistant_message_payload(message_id: str, version_id: str, *, text: str = "", status: str = "completed") -> dict:
    parts = [{"id": "text-1", "type": "text", "text": text, "status": status}] if text else []
    return {
        "id": message_id,
        "role": "assistant",
        "text": text,
        "parts": parts,
        "status": status,
        "meta": {"mcp_connected_servers": [], "mcp_errors": []},
        "current_version_id": version_id,
        "versions": [
            {
                "id": version_id,
                "version_index": 1,
                "kind": "original",
                "text": text,
                "parts": parts,
                "status": status,
                "meta": {"mcp_connected_servers": [], "mcp_errors": []},
                "feedback": None,
                "speech_status": None,
                "speech_mime_type": None,
                "created_at": "2026-04-05T00:00:01Z",
            }
        ],
        "can_regenerate": True,
        "created_at": "2026-04-05T00:00:01Z",
    }


class _FakeService:
    def __init__(self) -> None:
        self.feedback: str | None = None
        self.current_version_id = "ver-original-1"
        self.model_profile_key = "standard"

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def runtime_snapshot(self) -> dict:
        return {
            "ready": True,
            "mcp_connected_servers": ["demo"],
            "mcp_errors": [],
            "local_tools": ["get_current_time"],
            "mcp_tools": ["demo_search"],
        }

    async def stream_invoke(self, _user_id, _payload):
        yield "turn.start", {
            "thread_id": "t-1",
            "user_message": _user_message_payload("msg-user-stream-1", "帮我做一个3天杭州行程"),
            "assistant_message": _assistant_message_payload("msg-assistant-stream-1", "ver-stream-1", status="streaming"),
        }
        yield "part.delta", {
            "message_id": "msg-assistant-stream-1",
            "version_id": "ver-stream-1",
            "part_id": "text-1",
            "part_type": "text",
            "text_delta": "这是",
            "status": "streaming",
        }
        yield "tool.start", {
            "message_id": "msg-assistant-stream-1",
            "version_id": "ver-stream-1",
            "part": {
                "id": "tool-call-1",
                "type": "tool",
                "tool_call_id": "call-1",
                "tool_name": "get_current_time",
                "input": {},
                "output": None,
                "status": "running",
            },
        }
        yield "part.delta", {
            "message_id": "msg-assistant-stream-1",
            "version_id": "ver-stream-1",
            "part_id": "text-1",
            "part_type": "text",
            "text_delta": "一个测试回复",
            "status": "streaming",
        }
        yield "tool.done", {
            "message_id": "msg-assistant-stream-1",
            "version_id": "ver-stream-1",
            "part": {
                "id": "tool-call-1",
                "type": "tool",
                "tool_call_id": "call-1",
                "tool_name": "get_current_time",
                "input": {},
                "output": {"timezone": "Asia/Shanghai", "time": "21:02:21"},
                "status": "success",
            },
        }
        yield "message.completed", {
            "message": _assistant_message_payload("msg-assistant-stream-1", "ver-stream-1", text="这是一个测试回复"),
        }
        yield "turn.done", {"thread_id": "t-1"}

    def list_model_profiles(self) -> list[ChatModelProfile]:
        return [
            ChatModelProfile(key="standard", label="普通", kind="standard", is_default=True),
            ChatModelProfile(key="thinking", label="思考", kind="thinking", is_default=False),
        ]

    def list_sessions(self, _user_id: str) -> list[SessionSummary]:
        return [
            SessionSummary(
                thread_id="t-1",
                title="帮我做一个3天杭州...",
                created_at="2026-04-05T00:00:00Z",
                updated_at="2026-04-05T00:00:00Z",
                last_message_preview="帮我做一个3天杭州行程",
            )
        ]

    def get_session_detail(self, _user_id: str, thread_id: str) -> SessionDetail | None:
        if thread_id != "t-1":
            return None
        return SessionDetail(
            thread_id="t-1",
            title="帮我做一个3天杭州...",
            created_at="2026-04-05T00:00:00Z",
            updated_at="2026-04-05T00:00:00Z",
            model_profile_key=self.model_profile_key,
            messages=[
                PersistedChatMessage(
                    id="msg-user-1",
                    role="user",
                    text="帮我做一个3天杭州行程",
                    created_at="2026-04-05T00:00:00Z",
                ),
                PersistedChatMessage(
                    id="msg-assistant-1",
                    role="assistant",
                    text="这是一个测试回复" if self.current_version_id == "ver-original-1" else "这是重生成后的回复",
                    meta=ChatMetaInfo(
                        mcp_connected_servers=[],
                        mcp_errors=[],
                    ),
                    current_version_id=self.current_version_id,
                    versions=[
                        AssistantVersion(
                            id="ver-original-1",
                            version_index=1,
                            kind="original",
                            text="这是一个测试回复",
                            meta=ChatMetaInfo(
                                mcp_connected_servers=[],
                                mcp_errors=[],
                            ),
                            feedback=None,
                            speech_status="ready",
                            speech_mime_type="audio/mpeg",
                            created_at="2026-04-05T00:00:01Z",
                        ),
                        AssistantVersion(
                            id="ver-regenerated-1",
                            version_index=2,
                            kind="regenerated",
                            text="这是重生成后的回复",
                            meta=ChatMetaInfo(
                                mcp_connected_servers=[],
                                mcp_errors=[],
                            ),
                            feedback=self.feedback,  # type: ignore[arg-type]
                            speech_status="generating",
                            speech_mime_type="audio/mpeg",
                            created_at="2026-04-05T00:00:02Z",
                        ),
                    ],
                    can_regenerate=True,
                    created_at="2026-04-05T00:00:01Z",
                ),
            ],
        )

    def rename_session(self, _user_id: str, thread_id: str, title: str) -> SessionSummary | None:
        if thread_id != "t-1":
            return None
        return SessionSummary(
            thread_id="t-1",
            title=title,
            created_at="2026-04-05T00:00:00Z",
            updated_at="2026-04-05T00:00:02Z",
            last_message_preview="这是一个测试回复",
        )

    async def delete_session(self, _user_id: str, thread_id: str) -> bool:
        return thread_id == "t-1"

    def update_session_model_profile(self, _user_id: str, thread_id: str, model_profile_key: str):
        if thread_id != "t-1":
            return None
        if model_profile_key not in {"standard", "thinking"}:
            raise ValueError("Invalid model profile key")
        self.model_profile_key = model_profile_key
        return SessionModelProfileState(thread_id=thread_id, model_profile_key=model_profile_key)

    async def stream_regenerate(self, _user_id: str, thread_id: str, message_id: str):
        assert thread_id == "t-1"
        assert message_id == "msg-assistant-1"
        yield "turn.start", {
            "thread_id": thread_id,
            "assistant_message": _assistant_message_payload(message_id, "ver-regenerated-stream-1", status="streaming"),
        }
        yield "part.delta", {
            "message_id": message_id,
            "version_id": "ver-regenerated-stream-1",
            "part_id": "text-1",
            "part_type": "text",
            "text_delta": "新的重生成回复",
            "status": "streaming",
        }
        yield "message.completed", {
            "message": _assistant_message_payload(message_id, "ver-regenerated-stream-1", text="新的重生成回复"),
        }
        yield "turn.done", {"thread_id": thread_id}

    def switch_assistant_version(self, _user_id: str, thread_id: str, message_id: str, version_id: str):
        if thread_id != "t-1" or message_id != "msg-assistant-1" or version_id not in {"ver-original-1", "ver-regenerated-1"}:
            return None
        self.current_version_id = version_id
        detail = self.get_session_detail(_user_id, thread_id)
        assert detail is not None
        return detail.messages[1]

    def update_assistant_feedback(self, _user_id: str, thread_id: str, message_id: str, version_id: str, feedback: str | None):
        if thread_id != "t-1" or message_id != "msg-assistant-1" or version_id not in {"ver-original-1", "ver-regenerated-1"}:
            return None
        self.feedback = feedback
        detail = self.get_session_detail(_user_id, thread_id)
        assert detail is not None
        return detail.messages[1]

    def get_speech_playback_url(
        self,
        _user_id: str,
        thread_id: str,
        message_id: str,
        version_id: str,
        *,
        base_url: str,
    ) -> tuple[str, str]:
        if thread_id != "t-1" or message_id != "msg-assistant-1" or version_id not in {"ver-original-1", "ver-regenerated-1"}:
            raise FileNotFoundError("Speech asset not found")
        status = "ready" if version_id == "ver-original-1" else "generating"
        return f"{base_url}/api/speech/play/token-{version_id}", status

    def get_speech_playback_target(self, token: str) -> SpeechPlaybackTarget:
        if token not in {"token-ver-original-1", "token-ver-regenerated-1"}:
            raise ValueError("Invalid speech playback token")
        return SpeechPlaybackTarget(media_type="audio/mpeg", iterator=_fake_audio_stream())


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data_text = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            if line.startswith("data:"):
                data_text = line[5:].strip()
        if event_name and data_text:
            events.append((event_name, json.loads(data_text)))
    return events


def test_chat_stream_api_and_sessions_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(tmp_path / "chat.db"))
    fake_service = _FakeService()
    monkeypatch.setattr("app.main.get_agent_service", lambda: fake_service)
    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: fake_service
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="user-1",
        email="demo@example.com",
        nickname="demo",
        created_at="2026-04-05T00:00:00Z",
        updated_at="2026-04-05T00:00:00Z",
    )

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200

        response = client.post(
            "/api/chat/stream",
            json={
                "thread_id": "t-1",
                "user_message": "帮我做一个3天杭州行程",
                "locale": "zh-CN",
                "session_meta": {},
            },
        )
        assert response.status_code == 200

        events = _parse_sse(response.text)
        names = [event[0] for event in events]
        assert names == ["turn.start", "part.delta", "tool.start", "part.delta", "tool.done", "message.completed", "turn.done"]
        assert events[0][1]["assistant_message"]["status"] == "streaming"
        assert events[1][1]["text_delta"] == "这是"
        assert events[2][1]["part"]["tool_name"] == "get_current_time"
        assert events[4][1]["part"]["output"]["time"] == "21:02:21"
        assert events[5][1]["message"]["text"] == "这是一个测试回复"

        list_res = client.get("/api/sessions")
        assert list_res.status_code == 200
        assert list_res.json()[0]["thread_id"] == "t-1"

        profile_list_res = client.get("/api/chat/model-profiles")
        assert profile_list_res.status_code == 200
        assert profile_list_res.json()["default_profile_key"] == "standard"
        assert len(profile_list_res.json()["profiles"]) == 2

        detail_res = client.get("/api/sessions/t-1")
        assert detail_res.status_code == 200
        assert detail_res.json()["model_profile_key"] == "standard"
        assert detail_res.json()["messages"][0]["role"] == "user"
        assert detail_res.json()["messages"][1]["versions"][0]["kind"] == "original"
        assert detail_res.json()["messages"][1]["versions"][0]["speech_status"] == "ready"

        missing_detail = client.get("/api/sessions/not-exist")
        assert missing_detail.status_code == 404

        rename_res = client.patch("/api/sessions/t-1", json={"title": "杭州周末行"})
        assert rename_res.status_code == 200
        assert rename_res.json()["title"] == "杭州周末行"

        profile_update_res = client.patch(
            "/api/sessions/t-1/model-profile",
            json={"model_profile_key": "thinking"},
        )
        assert profile_update_res.status_code == 200
        assert profile_update_res.json()["model_profile_key"] == "thinking"

        regenerate_res = client.post("/api/sessions/t-1/messages/msg-assistant-1/regenerate/stream")
        assert regenerate_res.status_code == 200
        regenerate_events = _parse_sse(regenerate_res.text)
        assert [event[0] for event in regenerate_events] == ["turn.start", "part.delta", "message.completed", "turn.done"]

        switch_version_res = client.patch(
            "/api/sessions/t-1/messages/msg-assistant-1/current-version",
            json={"version_id": "ver-regenerated-1"},
        )
        assert switch_version_res.status_code == 200
        assert switch_version_res.json()["current_version_id"] == "ver-regenerated-1"

        feedback_res = client.patch(
            "/api/sessions/t-1/messages/msg-assistant-1/versions/ver-regenerated-1/feedback",
            json={"feedback": "up"},
        )
        assert feedback_res.status_code == 200
        assert feedback_res.json()["versions"][1]["feedback"] == "up"

        speech_url_res = client.get(
            "/api/sessions/t-1/messages/msg-assistant-1/versions/ver-regenerated-1/speech/playback-url"
        )
        assert speech_url_res.status_code == 200
        assert speech_url_res.json()["speech_status"] == "generating"
        assert speech_url_res.json()["playback_url"].endswith("/api/speech/play/token-ver-regenerated-1")

        speech_play_res = client.get("/api/speech/play/token-ver-regenerated-1")
        assert speech_play_res.status_code == 200
        assert speech_play_res.headers["content-type"].startswith("audio/mpeg")
        assert speech_play_res.content == b"fake-mp3-bytes"

        missing_rename = client.patch("/api/sessions/not-exist", json={"title": "x"})
        assert missing_rename.status_code == 404

        invalid_profile_update = client.patch(
            "/api/sessions/t-1/model-profile",
            json={"model_profile_key": "unknown"},
        )
        assert invalid_profile_update.status_code == 400

        delete_res = client.delete("/api/sessions/t-1")
        assert delete_res.status_code == 200
        assert delete_res.json()["deleted"] is True

        missing_delete = client.delete("/api/sessions/not-exist")
        assert missing_delete.status_code == 404

        invalid_speech_play = client.get("/api/speech/play/not-valid")
        assert invalid_speech_play.status_code == 401

    app.dependency_overrides.clear()


def test_regenerate_stream_returns_business_error_when_limit_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(tmp_path / "chat.db"))

    class _LimitFakeService(_FakeService):
        async def stream_regenerate(self, _user_id: str, thread_id: str, message_id: str):
            assert thread_id == "t-1"
            assert message_id == "msg-assistant-1"
            if False:
                yield "messages", {}
            raise ValueError("最多生成三次无法重新生成")

    fake_service = _LimitFakeService()
    monkeypatch.setattr("app.main.get_agent_service", lambda: fake_service)
    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: fake_service
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="user-1",
        email="demo@example.com",
        nickname="demo",
        created_at="2026-04-05T00:00:00Z",
        updated_at="2026-04-05T00:00:00Z",
    )

    with TestClient(app) as client:
        regenerate_res = client.post("/api/sessions/t-1/messages/msg-assistant-1/regenerate/stream")
        assert regenerate_res.status_code == 200
        regenerate_events = _parse_sse(regenerate_res.text)
        assert regenerate_events == [("error", {"message": "最多生成三次无法重新生成"})]

    app.dependency_overrides.clear()


def test_chat_stream_hides_internal_exception_details(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(tmp_path / "chat.db"))

    class _CrashedService(_FakeService):
        async def stream_invoke(self, _user_id: str, _payload):
            if False:
                yield "turn.start", {}
            raise RuntimeError("provider exploded with internal details")

    fake_service = _CrashedService()
    monkeypatch.setattr("app.main.get_agent_service", lambda: fake_service)
    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: fake_service
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="user-1",
        email="demo@example.com",
        nickname="demo",
        created_at="2026-04-05T00:00:00Z",
        updated_at="2026-04-05T00:00:00Z",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream",
            json={
                "thread_id": "t-1",
                "user_message": "帮我做一个3天杭州行程",
                "locale": "zh-CN",
                "session_meta": {},
            },
        )
        assert response.status_code == 200
        assert _parse_sse(response.text) == [("error", {"message": "请求失败，请稍后重试。"})]

    app.dependency_overrides.clear()
