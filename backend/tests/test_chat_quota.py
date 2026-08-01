"""聊天接口扣次测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_agent_service, get_payment_service
from app.auth.store import AuthSQLiteStore
from app.db.bootstrap import bootstrap_sqlite_database
from app.main import create_app
from app.payment.service import PaymentService


class _FakeAgentService:
    """记录 stream_invoke 调用次数的假 Agent 服务。"""

    def __init__(self) -> None:
        self.stream_invoke_calls = 0

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def runtime_snapshot(self) -> dict:
        return {"ready": False, "mcp_connected_servers": [], "mcp_errors": [], "local_tools": [], "mcp_tools": []}

    async def stream_invoke(self, _user_id, _payload):
        self.stream_invoke_calls += 1
        yield "turn.start", {"thread_id": "t-1"}
        yield "turn.done", {"thread_id": "t-1"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client: TestClient, email: str = "quota@example.com") -> str:
    send = client.post("/api/auth/send-code", json={"email": email, "purpose": "register"})
    assert send.status_code == 200
    verify = client.post(
        "/api/auth/verify-code",
        json={"email": email, "code": "123456", "purpose": "register"},
    )
    assert verify.status_code == 200
    return verify.json()["access_token"]


def _user_id(db_path: Path, email: str = "quota@example.com") -> str:
    user = AuthSQLiteStore(db_path).get_user_by_email(email)
    assert user is not None
    return user.id


def _chat_payload() -> dict:
    return {
        "thread_id": "t-1",
        "user_message": "帮我做一个3天杭州行程",
        "locale": "zh-CN",
        "session_meta": {},
    }


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


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return bootstrap_sqlite_database(tmp_path / "payment.db")


@pytest.fixture()
def payment_service(db_path: Path) -> PaymentService:
    return PaymentService(sqlite_db_path=db_path)


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    payment_service: PaymentService,
) -> tuple[TestClient, _FakeAgentService]:
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-chat-quota-0123456789")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "demo")
    monkeypatch.setenv("SMTP_PASSWORD", "demo")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.setattr("app.auth.service.secrets.randbelow", lambda _limit: 123456)
    monkeypatch.setattr("app.auth.service.AuthService._send_email", lambda self, **_kwargs: None)
    fake_agent = _FakeAgentService()
    monkeypatch.setattr("app.main.get_agent_service", lambda: fake_agent)
    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()

    app = create_app()
    app.dependency_overrides[get_agent_service] = lambda: fake_agent
    app.dependency_overrides[get_payment_service] = lambda: payment_service
    with TestClient(app) as test_client:
        yield test_client, fake_agent

    app.dependency_overrides.clear()
    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()


def test_chat_requires_auth(client: tuple[TestClient, _FakeAgentService]) -> None:
    test_client, _ = client
    response = test_client.post("/api/chat/stream", json=_chat_payload())
    assert response.status_code == 401


def test_chat_consumes_free_quota(
    client: tuple[TestClient, _FakeAgentService],
    payment_service: PaymentService,
    db_path: Path,
) -> None:
    test_client, _ = client
    token = _register_and_login(test_client)
    user_id = _user_id(db_path)

    response = test_client.post("/api/chat/stream", json=_chat_payload(), headers=_auth(token))
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [event[0] for event in events] == ["turn.start", "turn.done"]

    subscription = payment_service.get_subscription(user_id)
    assert subscription["free_used"] == 1
    assert subscription["remain_count"] == 0


def test_chat_consumes_purchased_quota(
    client: tuple[TestClient, _FakeAgentService],
    payment_service: PaymentService,
    db_path: Path,
) -> None:
    test_client, _ = client
    token = _register_and_login(test_client)
    user_id = _user_id(db_path)
    payment_service._store.grant_quota(user_id, 5)
    for _ in range(10):
        payment_service.consume(user_id)

    response = test_client.post("/api/chat/stream", json=_chat_payload(), headers=_auth(token))
    assert response.status_code == 200
    assert [event[0] for event in _parse_sse(response.text)] == ["turn.start", "turn.done"]

    subscription = payment_service.get_subscription(user_id)
    assert subscription["free_used"] == 10
    assert subscription["remain_count"] == 4


def test_chat_quota_exhausted_returns_sse_error(
    client: tuple[TestClient, _FakeAgentService],
    payment_service: PaymentService,
    db_path: Path,
) -> None:
    test_client, fake_agent = client
    token = _register_and_login(test_client)
    user_id = _user_id(db_path)
    for _ in range(10):
        payment_service.consume(user_id)

    response = test_client.post("/api/chat/stream", json=_chat_payload(), headers=_auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert len(events) == 1
    assert events[0][0] == "error"
    assert "订阅" in events[0][1]["message"]
    assert fake_agent.stream_invoke_calls == 0
