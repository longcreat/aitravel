from __future__ import annotations

from contextlib import contextmanager

from app.observability.langsmith import is_langsmith_tracing_enabled, langsmith_trace_context


def test_langsmith_trace_context_respects_disabled_env(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    assert is_langsmith_tracing_enabled() is False

    with langsmith_trace_context("chat.stream", user_id="u1", thread_id="t1"):
        pass


def test_langsmith_trace_context_passes_project_tags_and_metadata(monkeypatch):
    captured: dict[str, object] = {}

    @contextmanager
    def _fake_tracing_context(**kwargs):
        captured.update(kwargs)
        yield

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_PROJECT", "demo-project")
    monkeypatch.setattr("app.observability.langsmith.tracing_context", _fake_tracing_context)

    with langsmith_trace_context(
        "chat.stream",
        user_id="u1",
        thread_id="t1",
        locale="zh-CN",
        extra_metadata={"session_meta_keys": ["timezone"]},
    ):
        pass

    assert captured["project_name"] == "demo-project"
    assert captured["enabled"] is True
    assert captured["tags"] == ["ai-travel-agent", "chat.stream"]
    assert captured["metadata"] == {
        "operation": "chat.stream",
        "user_id": "u1",
        "thread_id": "t1",
        "locale": "zh-CN",
        "session_meta_keys": ["timezone"],
    }

