from __future__ import annotations

from pathlib import Path

import pytest

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
    sent_subjects: list[str] = []
    sent_plain_parts: list[str] = []
    sent_html_parts: list[str] = []
    multipart_flags: list[bool] = []

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
            sent_subjects.append(str(message["Subject"]))
            multipart_flags.append(message.is_multipart())
            plain_part = message.get_body(preferencelist=("plain",))
            sent_plain_parts.append(plain_part.get_content() if plain_part else "")
            html_part = message.get_body(preferencelist=("html",))
            sent_html_parts.append(html_part.get_content() if html_part else "")
            return None

    def _unexpected_smtp(*args, **kwargs):
        raise AssertionError("port 994 should use SMTP_SSL instead of SMTP")

    monkeypatch.setattr("app.auth.service.smtplib.SMTP_SSL", _FakeSMTPSSL)
    monkeypatch.setattr("app.auth.service.smtplib.SMTP", _unexpected_smtp)

    service = AuthService(sqlite_db_path=db_path)
    service._send_email(email="user@example.com", code="123456", purpose="login")

    assert calls == [("smtp.test.local", 994)]
    assert sent_subjects == ["你的 WANDER AI 代码为 123456"]
    assert multipart_flags == [True]
    assert "WANDER AI 验证码" in sent_plain_parts[0]
    assert "123456" in sent_plain_parts[0]
    assert "WANDER AI" in sent_html_parts[0]
    assert "123456" in sent_html_parts[0]
    assert "输入此临时验证码以继续登录" in sent_html_parts[0]


def test_auth_service_uses_starttls_for_port_587(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    _set_base_env(monkeypatch, db_path, "587")

    events: list[str] = []
    sent_subjects: list[str] = []
    sent_plain_parts: list[str] = []
    sent_html_parts: list[str] = []
    multipart_flags: list[bool] = []

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
            sent_subjects.append(str(message["Subject"]))
            multipart_flags.append(message.is_multipart())
            plain_part = message.get_body(preferencelist=("plain",))
            sent_plain_parts.append(plain_part.get_content() if plain_part else "")
            html_part = message.get_body(preferencelist=("html",))
            sent_html_parts.append(html_part.get_content() if html_part else "")

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
    assert sent_subjects == ["你的 WANDER AI 代码为 123456"]
    assert multipart_flags == [True]
    assert "WANDER AI 验证码" in sent_plain_parts[0]
    assert "123456" in sent_plain_parts[0]
    assert "继续注册" in sent_plain_parts[0]
    assert "WANDER AI" in sent_html_parts[0]
    assert "123456" in sent_html_parts[0]
    assert "输入此临时验证码以继续注册" in sent_html_parts[0]


def test_auth_service_requires_jwt_secret(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(db_path))

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        AuthService(sqlite_db_path=db_path)
