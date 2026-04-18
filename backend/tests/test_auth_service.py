from __future__ import annotations

from pathlib import Path

from app.auth.service import AuthService


def _set_base_env(monkeypatch, db_path: Path, port: str) -> None:
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-auth-service-0123456789")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", port)
    monkeypatch.setenv("SMTP_USERNAME", "demo@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("SMTP_FROM", "demo@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")


def test_auth_service_uses_smtp_ssl_for_port_994(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    _set_base_env(monkeypatch, db_path, "994")

    calls: list[tuple[str, int]] = []

    class _FakeSMTPSSL:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append((host, port))

        def __enter__(self) -> "_FakeSMTPSSL":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            return None

        def send_message(self, message) -> None:
            return None

    def _unexpected_smtp(*args, **kwargs):
        raise AssertionError("port 994 should use SMTP_SSL instead of SMTP")

    monkeypatch.setattr("app.auth.service.smtplib.SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr("app.auth.service.smtplib.SMTP", _unexpected_smtp)

    service = AuthService(sqlite_db_path=db_path)
    service._send_email(email="user@example.com", code="123456", purpose="login")

    assert calls == [("smtp.test.local", 994)]


def test_auth_service_uses_starttls_for_port_587(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    _set_base_env(monkeypatch, db_path, "587")

    events: list[str] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            events.append(f"connect:{host}:{port}")

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def ehlo(self) -> None:
            events.append("ehlo")

        def starttls(self) -> None:
            events.append("starttls")

        def login(self, username: str, password: str) -> None:
            events.append(f"login:{username}")

        def send_message(self, message) -> None:
            events.append("send")

    def _unexpected_smtp_ssl(*args, **kwargs):
        raise AssertionError("port 587 should use SMTP + STARTTLS instead of SMTP_SSL")

    monkeypatch.setattr("app.auth.service.smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr("app.auth.service.smtplib.SMTP_SSL", _unexpected_smtp_ssl)

    service = AuthService(sqlite_db_path=db_path)
    service._send_email(email="user@example.com", code="123456", purpose="register")

    assert events == [
        "connect:smtp.test.local:587",
        "ehlo",
        "starttls",
        "ehlo",
        "login:demo@example.com",
        "send",
    ]
