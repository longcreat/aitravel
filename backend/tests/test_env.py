from __future__ import annotations

import os

from app.env import load_app_env


def test_load_app_env_preserves_dollar_signs(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SMTP_PASSWORD=abc$def${NOT_A_VAR}",
                "JWT_SECRET=from-env-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("NOT_A_VAR", "expanded")

    load_app_env(env_file)

    assert os.getenv("SMTP_PASSWORD") == "abc$def${NOT_A_VAR}"
    assert os.getenv("JWT_SECRET") == "from-env-file"


def test_load_app_env_does_not_override_process_env(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEV_RESET_CHAT_DB=false\n", encoding="utf-8")
    monkeypatch.setenv("DEV_RESET_CHAT_DB", "true")

    load_app_env(env_file)

    assert os.getenv("DEV_RESET_CHAT_DB") == "true"
