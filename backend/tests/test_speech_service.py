from __future__ import annotations

from app.memory.sqlite_store import ChatSQLiteStore
from app.speech.service import SpeechService


def test_speech_service_requires_explicit_tts_api_key(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "llm-only-key")
    monkeypatch.delenv("ALIYUN_TTS_API_KEY", raising=False)

    db_path = tmp_path / "chat.db"
    service = SpeechService(chat_store=ChatSQLiteStore(db_path), sqlite_db_path=db_path)

    assert service.enabled is False
