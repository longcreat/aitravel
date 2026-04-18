from __future__ import annotations

from app.llm.provider import (
    build_chat_model,
    coerce_llm_profile_key,
    get_llm_configurable,
    list_llm_profiles,
    load_llm_profile_registry,
    resolve_llm_profile_key,
)


def test_build_chat_model_uses_init_chat_model_with_runtime_configurable_fields(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_init_chat_model(model, *, model_provider=None, **kwargs):
        captured["model"] = model
        captured["model_provider"] = model_provider
        captured["kwargs"] = kwargs
        return "fake-chat-model"

    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "standard")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "demo-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.4")
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr("app.llm.provider.init_chat_model", _fake_init_chat_model)

    result = build_chat_model()

    assert result == "fake-chat-model"
    assert captured["model"] == "demo-standard-model"
    assert captured["model_provider"] == "openai"
    assert captured["kwargs"] == {
        "temperature": 0.4,
        "api_key": "demo-key",
        "base_url": "https://example.com/v1",
        "configurable_fields": ("model", "model_provider", "temperature"),
        "config_prefix": "llm",
    }


def test_load_llm_profile_registry_reads_standard_and_thinking_profiles(monkeypatch):
    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "thinking")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_LABEL", "普通")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_LABEL", "思考")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "thinking-model")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.6")

    registry = load_llm_profile_registry()

    assert registry.default_profile_key == "thinking"
    assert registry.profiles["standard"].label == "普通"
    assert registry.profiles["standard"].model == "standard-model"
    assert registry.profiles["thinking"].label == "思考"
    assert registry.profiles["thinking"].temperature == 0.6


def test_profile_resolution_and_configurable_values(monkeypatch):
    monkeypatch.delenv("LLM_PROFILE_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_PROFILE_STANDARD_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROFILE_THINKING_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    monkeypatch.setenv("LLM_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")

    profiles = list_llm_profiles()

    assert [profile.key for profile in profiles] == ["standard", "thinking"]
    assert resolve_llm_profile_key(None) == "standard"
    assert resolve_llm_profile_key("thinking") == "thinking"
    assert coerce_llm_profile_key("missing") == "standard"
    assert get_llm_configurable("thinking") == {
        "llm_model": "shared-model",
        "llm_model_provider": "openai",
        "llm_temperature": 0.2,
    }


def test_build_chat_model_uses_qwen_adapter_for_qwen_provider(monkeypatch):
    captured: dict[str, object] = {}

    class _FakePatchedQwenChatOpenAI:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def configurable_fields(self, **kwargs):
            captured["configurable_fields"] = kwargs
            return "fake-qwen-chat-model"

    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "thinking")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "qwen3-8b")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.4")
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr("app.llm.provider.PatchedQwenChatOpenAI", _FakePatchedQwenChatOpenAI)

    result = build_chat_model()

    assert result == "fake-qwen-chat-model"
    assert captured["kwargs"] == {
        "model": "qwen3-8b",
        "model_provider": "qwen",
        "temperature": 0.4,
        "api_key": "demo-key",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "extra_body": {"enable_thinking": True},
    }
    configurable_fields = captured["configurable_fields"]
    assert set(configurable_fields.keys()) == {"model_name", "model_provider", "temperature", "extra_body"}
    assert configurable_fields["model_name"].id == "llm_model"
    assert configurable_fields["extra_body"].id == "llm_extra_body"


def test_get_llm_configurable_includes_qwen_thinking_extra_body(monkeypatch):
    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "standard")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "qwen3-8b")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.4")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    assert get_llm_configurable("thinking") == {
        "llm_model": "qwen3-8b",
        "llm_model_provider": "qwen",
        "llm_temperature": 0.4,
        "llm_extra_body": {"enable_thinking": True},
    }
