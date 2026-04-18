from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import deps
from app.main import create_app


class _NoopAgentService:
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def runtime_snapshot(self) -> dict:
        return {"ready": False, "mcp_connected_servers": [], "mcp_errors": [], "local_tools": [], "mcp_tools": []}


def test_auth_send_code_verify_and_me(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-auth-api-0123456789")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "demo")
    monkeypatch.setenv("SMTP_PASSWORD", "demo")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")

    deps.get_auth_service.cache_clear()
    deps.get_agent_service.cache_clear()
    monkeypatch.setattr("app.main.get_agent_service", lambda: _NoopAgentService())
    monkeypatch.setattr("app.auth.service.secrets.randbelow", lambda _limit: 123456)
    monkeypatch.setattr("app.auth.service.AuthService._send_email", lambda self, **_kwargs: None)

    app = create_app()

    with TestClient(app) as client:
        register_send = client.post("/api/auth/send-code", json={"email": "demo@example.com", "purpose": "register"})
        assert register_send.status_code == 200
        assert register_send.json()["sent"] is True

        register_verify = client.post(
            "/api/auth/verify-code",
            json={"email": "demo@example.com", "code": "123456", "purpose": "register"},
        )
        assert register_verify.status_code == 200
        payload = register_verify.json()
        assert payload["access_token"]
        assert payload["user"]["email"] == "demo@example.com"

        duplicate_register = client.post(
            "/api/auth/send-code",
            json={"email": "demo@example.com", "purpose": "register"},
        )
        assert duplicate_register.status_code == 409

        login_send = client.post("/api/auth/send-code", json={"email": "demo@example.com", "purpose": "login"})
        assert login_send.status_code == 200

        wrong_code = client.post(
            "/api/auth/verify-code",
            json={"email": "demo@example.com", "code": "654321", "purpose": "login"},
        )
        assert wrong_code.status_code == 400

        login_verify = client.post(
            "/api/auth/verify-code",
            json={"email": "demo@example.com", "code": "123456", "purpose": "login"},
        )
        assert login_verify.status_code == 200
        access_token = login_verify.json()["access_token"]

        me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me_response.status_code == 200
        assert me_response.json()["nickname"] == "demo"

    deps.get_auth_service.cache_clear()
    deps.get_agent_service.cache_clear()
