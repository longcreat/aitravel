from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.deps import get_agent_service
from app.main import create_app
from app.schemas.chat import PersistedChatMessage, SessionDetail, SessionSummary


class _FakeService:
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

    async def stream_invoke(self, _payload):
        yield "messages", {
            "type": "messages",
            "ns": [],
            "data": [
                {
                    "type": "AIMessageChunk",
                    "data": {
                        "content": "这是",
                        "additional_kwargs": {},
                        "response_metadata": {},
                        "type": "AIMessageChunk",
                        "name": None,
                        "id": "chunk-1",
                        "tool_calls": [],
                        "invalid_tool_calls": [],
                        "usage_metadata": None,
                        "tool_call_chunks": [],
                        "chunk_position": None,
                    },
                },
                {"langgraph_node": "model"},
            ],
        }
        yield "updates", {
            "type": "updates",
            "ns": [],
            "data": {
                "model": {
                    "messages": [
                        {
                            "type": "ai",
                            "data": {
                                "content": "我先调用预算工具。",
                                "additional_kwargs": {},
                                "response_metadata": {},
                                "type": "ai",
                                "name": None,
                                "id": None,
                                "tool_calls": [{"name": "get_current_time", "args": {}, "id": "call-1", "type": "tool_call"}],
                                "invalid_tool_calls": [],
                                "usage_metadata": None,
                            },
                        }
                    ]
                }
            },
        }
        yield "messages", {
            "type": "messages",
            "ns": [],
            "data": [
                {
                    "type": "AIMessageChunk",
                    "data": {
                        "content": "一个测试回复",
                        "additional_kwargs": {},
                        "response_metadata": {},
                        "type": "AIMessageChunk",
                        "name": None,
                        "id": "chunk-2",
                        "tool_calls": [],
                        "invalid_tool_calls": [],
                        "usage_metadata": None,
                        "tool_call_chunks": [],
                        "chunk_position": None,
                    },
                },
                {"langgraph_node": "model"},
            ],
        }
        yield "updates", {
            "type": "updates",
            "ns": [],
            "data": {
                "tools": {
                    "messages": [
                        {
                            "type": "tool",
                            "data": {
                                "content": "{\"timezone\":\"Asia/Shanghai\",\"time\":\"21:02:21\"}",
                                "additional_kwargs": {},
                                "response_metadata": {},
                                "type": "tool",
                                "name": "get_current_time",
                                "id": None,
                                "tool_call_id": "call-1",
                                "artifact": None,
                                "status": "success",
                            },
                        }
                    ]
                }
            },
        }
        yield "values", {
            "type": "values",
            "ns": [],
            "data": {
                "messages": [
                    {"type": "ai", "data": {"content": "这是一个测试回复", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": None, "id": None, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": None}}
                ],
            },
        }

    def list_sessions(self) -> list[SessionSummary]:
        return [
            SessionSummary(
                thread_id="t-1",
                title="帮我做一个3天杭州...",
                created_at="2026-04-05T00:00:00Z",
                updated_at="2026-04-05T00:00:00Z",
                last_message_preview="帮我做一个3天杭州行程",
            )
        ]

    def get_session_detail(self, thread_id: str) -> SessionDetail | None:
        if thread_id != "t-1":
            return None
        return SessionDetail(
            thread_id="t-1",
            title="帮我做一个3天杭州...",
            created_at="2026-04-05T00:00:00Z",
            updated_at="2026-04-05T00:00:00Z",
            messages=[
                PersistedChatMessage(
                    id=1,
                    role="user",
                    text="帮我做一个3天杭州行程",
                    created_at="2026-04-05T00:00:00Z",
                ),
                PersistedChatMessage(
                    id=2,
                    role="assistant",
                    text="这是一个测试回复",
                    created_at="2026-04-05T00:00:01Z",
                ),
            ],
        )

    def rename_session(self, thread_id: str, title: str) -> SessionSummary | None:
        if thread_id != "t-1":
            return None
        return SessionSummary(
            thread_id="t-1",
            title=title,
            created_at="2026-04-05T00:00:00Z",
            updated_at="2026-04-05T00:00:02Z",
            last_message_preview="这是一个测试回复",
        )

    async def delete_session(self, thread_id: str) -> bool:
        return thread_id == "t-1"


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


def test_chat_stream_api_and_sessions_api() -> None:
    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: _FakeService()

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
        assert names == ["messages", "updates", "messages", "updates", "values"]
        assert events[0][1]["data"][0]["data"]["content"] == "这是"
        assert events[2][1]["data"][0]["data"]["content"] == "一个测试回复"
        assert events[4][1]["data"]["messages"][0]["data"]["content"] == "这是一个测试回复"

        list_res = client.get("/api/sessions")
        assert list_res.status_code == 200
        assert list_res.json()[0]["thread_id"] == "t-1"

        detail_res = client.get("/api/sessions/t-1")
        assert detail_res.status_code == 200
        assert detail_res.json()["messages"][0]["role"] == "user"

        missing_detail = client.get("/api/sessions/not-exist")
        assert missing_detail.status_code == 404

        rename_res = client.patch("/api/sessions/t-1", json={"title": "杭州周末行"})
        assert rename_res.status_code == 200
        assert rename_res.json()["title"] == "杭州周末行"

        missing_rename = client.patch("/api/sessions/not-exist", json={"title": "x"})
        assert missing_rename.status_code == 404

        delete_res = client.delete("/api/sessions/t-1")
        assert delete_res.status_code == 200
        assert delete_res.json()["deleted"] is True

        missing_delete = client.delete("/api/sessions/not-exist")
        assert missing_delete.status_code == 404
