from __future__ import annotations

from langchain_qwq import ChatQwen

from app.llm.provider import (
    build_chat_model_for_profile,
    build_chat_models_by_profile,
    coerce_llm_profile_key,
    list_llm_profiles,
    load_llm_profile_registry,
    resolve_llm_profile_key,
)


def test_build_chat_model_for_profile_uses_init_chat_model_for_openai(monkeypatch):
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

    result = build_chat_model_for_profile("standard")

    assert result == "fake-chat-model"
    assert captured["model"] == "demo-standard-model"
    assert captured["model_provider"] == "openai"
    # 新实现不再走 configurable_fields，所以 kwargs 里只剩固化的连接参数
    assert captured["kwargs"] == {
        "temperature": 0.4,
        "api_key": "demo-key",
        "base_url": "https://example.com/v1",
    }


def test_build_chat_model_for_profile_uses_chat_qwen_with_thinking(monkeypatch):
    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "standard")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwen-plus")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "qwen3-8b")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.4")
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    standard = build_chat_model_for_profile("standard")
    thinking = build_chat_model_for_profile("thinking")

    assert isinstance(standard, ChatQwen)
    assert isinstance(thinking, ChatQwen)
    # Qwen3 / qwen-plus 等混合思考模型必须显式区分 enable_thinking
    assert standard.enable_thinking is False
    assert thinking.enable_thinking is True
    assert thinking.model_name == "qwen3-8b"
    assert thinking.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert thinking.temperature == 0.4


def test_build_chat_model_for_profile_skips_enable_thinking_for_qwq(monkeypatch):
    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "standard")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "qwq-32b")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "qwq-32b")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.2")
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    model = build_chat_model_for_profile("thinking")

    assert isinstance(model, ChatQwen)
    # QwQ 是纯思考模型，不应该传 enable_thinking 字段（保持 SDK 默认）
    assert model.enable_thinking is None


def test_build_chat_models_by_profile_returns_one_per_profile(monkeypatch):
    init_calls: list[tuple[str, dict]] = []

    def _fake_init_chat_model(model, *, model_provider=None, **kwargs):
        init_calls.append((model, kwargs))
        return f"chat-model-{model}"

    monkeypatch.setenv("LLM_PROFILE_DEFAULT", "standard")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "model-a")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_PROFILE_THINKING_MODEL", "model-b")
    monkeypatch.setenv("LLM_PROFILE_THINKING_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_THINKING_TEMPERATURE", "0.4")
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr("app.llm.provider.init_chat_model", _fake_init_chat_model)

    models = build_chat_models_by_profile()

    assert set(models.keys()) == {"standard", "thinking"}
    assert models["standard"] == "chat-model-model-a"
    assert models["thinking"] == "chat-model-model-b"
    assert {entry[0] for entry in init_calls} == {"model-a", "model-b"}


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


def test_profile_resolution(monkeypatch):
    monkeypatch.delenv("LLM_PROFILE_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_PROFILE_STANDARD_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROFILE_STANDARD_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROFILE_STANDARD_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_PROFILE_THINKING_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROFILE_THINKING_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROFILE_THINKING_TEMPERATURE", raising=False)
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    monkeypatch.setenv("LLM_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")

    profiles = list_llm_profiles()

    assert [profile.key for profile in profiles] == ["standard", "thinking"]
    assert resolve_llm_profile_key(None) == "standard"
    assert resolve_llm_profile_key("thinking") == "thinking"
    assert coerce_llm_profile_key("missing") == "standard"
