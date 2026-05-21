"""Connector secret encryption tests."""

from __future__ import annotations

import importlib

import pytest


def _reload_crypto():
    import app.connectors.crypto as module

    importlib.reload(module)
    return module


def test_round_trip_with_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TOKEN_ENC_KEY", "test-key-test-key-test-key-test-key")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    crypto = _reload_crypto()

    cipher = crypto.encrypt_secret("hello world")
    assert cipher != "hello world"
    assert crypto.decrypt_secret(cipher) == "hello world"


def test_falls_back_to_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_TOKEN_ENC_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET", "fallback-secret-fallback-secret-fall")
    crypto = _reload_crypto()
    cipher = crypto.encrypt_secret("payload")
    assert crypto.decrypt_secret(cipher) == "payload"


def test_missing_keys_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_TOKEN_ENC_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    crypto = _reload_crypto()
    with pytest.raises(RuntimeError):
        crypto.encrypt_secret("payload")


def test_decrypt_handles_empty() -> None:
    crypto = _reload_crypto()
    assert crypto.decrypt_secret(None) is None
    assert crypto.decrypt_secret("") is None
