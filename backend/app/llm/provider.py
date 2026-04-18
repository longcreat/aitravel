"""LLM 提供方与模型档位配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import ConfigurableField

from app.llm.qwen_chat_openai import PatchedQwenChatOpenAI


ChatModelProfileKind = Literal["standard", "thinking"]


@dataclass(frozen=True)
class LLMConnectionSettings:
    """模型连接层配置。"""

    api_key: str | None
    base_url: str | None


@dataclass(frozen=True)
class LLMProfile:
    """单个模型档位。"""

    key: str
    label: str
    kind: ChatModelProfileKind
    model: str
    model_provider: str
    temperature: float


@dataclass(frozen=True)
class LLMProfileRegistry:
    """模型档位注册表。"""

    default_profile_key: str
    profiles: dict[str, LLMProfile]


def _normalize_provider(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def load_llm_connection_settings() -> LLMConnectionSettings:
    """读取连接层配置。"""
    return LLMConnectionSettings(
        api_key=_env("OPENAI_API_KEY"),
        base_url=_env("OPENAI_BASE_URL"),
    )


def _is_dashscope_base_url(base_url: str | None) -> bool:
    return bool(base_url and "dashscope" in base_url.lower())


def _is_qwen_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("qwen") or normalized.startswith("qwq")


def _uses_qwen_chat_adapter(profile: LLMProfile, connection: LLMConnectionSettings) -> bool:
    normalized_provider = _normalize_provider(profile.model_provider)
    if normalized_provider == "qwen":
        return True
    return normalized_provider == "openai" and _is_dashscope_base_url(connection.base_url) and _is_qwen_model(profile.model)


def _build_qwen_extra_body(profile: LLMProfile) -> dict[str, Any] | None:
    normalized_model = profile.model.strip().lower()
    if normalized_model.startswith("qwq") or "thinking" in normalized_model:
        return None
    return {"enable_thinking": profile.kind == "thinking"}


def load_llm_profile_registry() -> LLMProfileRegistry:
    """从环境变量读取当前可用模型档位。"""
    standard_model = _env("LLM_PROFILE_STANDARD_MODEL", _env("LLM_MODEL", "gpt-4.1-mini"))
    standard_provider = _env("LLM_PROFILE_STANDARD_PROVIDER", _env("LLM_MODEL_PROVIDER", "openai"))
    standard_temperature = float(_env("LLM_PROFILE_STANDARD_TEMPERATURE", _env("LLM_TEMPERATURE", "0.2")) or "0.2")

    thinking_model = _env("LLM_PROFILE_THINKING_MODEL", standard_model)
    thinking_provider = _env("LLM_PROFILE_THINKING_PROVIDER", standard_provider)
    thinking_temperature = float(
        _env("LLM_PROFILE_THINKING_TEMPERATURE", _env("LLM_TEMPERATURE", "0.2")) or "0.2"
    )

    profiles = {
        "standard": LLMProfile(
            key="standard",
            label=_env("LLM_PROFILE_STANDARD_LABEL", "普通") or "普通",
            kind="standard",
            model=standard_model or "gpt-4.1-mini",
            model_provider=standard_provider or "openai",
            temperature=standard_temperature,
        ),
        "thinking": LLMProfile(
            key="thinking",
            label=_env("LLM_PROFILE_THINKING_LABEL", "思考") or "思考",
            kind="thinking",
            model=thinking_model or standard_model or "gpt-4.1-mini",
            model_provider=thinking_provider or standard_provider or "openai",
            temperature=thinking_temperature,
        ),
    }

    default_profile_key = _env("LLM_PROFILE_DEFAULT", "standard") or "standard"
    if default_profile_key not in profiles:
        raise ValueError(f"Invalid default LLM profile key: {default_profile_key}")

    return LLMProfileRegistry(default_profile_key=default_profile_key, profiles=profiles)


def get_default_llm_profile_key() -> str:
    """返回默认模型档位 key。"""
    return load_llm_profile_registry().default_profile_key


def list_llm_profiles() -> list[LLMProfile]:
    """按稳定顺序返回全部可用档位。"""
    registry = load_llm_profile_registry()
    order = ("standard", "thinking")
    return [registry.profiles[key] for key in order if key in registry.profiles]


def resolve_llm_profile_key(requested_key: str | None) -> str:
    """解析用户显式请求的模型档位。"""
    registry = load_llm_profile_registry()
    if requested_key is None or not requested_key.strip():
        return registry.default_profile_key

    normalized = requested_key.strip()
    if normalized not in registry.profiles:
        raise ValueError("Invalid model profile key")
    return normalized


def coerce_llm_profile_key(stored_key: str | None) -> str:
    """把持久化里的模型档位收敛到当前仍有效的 key。"""
    registry = load_llm_profile_registry()
    if stored_key and stored_key in registry.profiles:
        return stored_key
    return registry.default_profile_key


def get_llm_profile(profile_key: str | None) -> LLMProfile:
    """读取指定模型档位；未知 key 自动回退默认值。"""
    registry = load_llm_profile_registry()
    resolved_key = coerce_llm_profile_key(profile_key)
    return registry.profiles[resolved_key]


def get_llm_configurable(profile_key: str | None) -> dict[str, Any]:
    """生成写入 LangChain runtime configurable 的模型配置。"""
    profile = get_llm_profile(profile_key)
    connection = load_llm_connection_settings()
    configurable = {
        "llm_model": profile.model,
        "llm_model_provider": profile.model_provider,
        "llm_temperature": profile.temperature,
    }
    if _uses_qwen_chat_adapter(profile, connection):
        extra_body = _build_qwen_extra_body(profile)
        if extra_body is not None:
            configurable["llm_extra_body"] = extra_body
    return configurable


def build_chat_model() -> BaseChatModel:
    """构建 LangChain 官方 runtime-configurable 聊天模型。"""
    profile = get_llm_profile(get_default_llm_profile_key())
    connection = load_llm_connection_settings()
    if _uses_qwen_chat_adapter(profile, connection):
        return PatchedQwenChatOpenAI(
            model=profile.model,
            model_provider="qwen",
            temperature=profile.temperature,
            api_key=connection.api_key,
            base_url=connection.base_url,
            extra_body=_build_qwen_extra_body(profile),
        ).configurable_fields(
            model_name=ConfigurableField(id="llm_model"),
            model_provider=ConfigurableField(id="llm_model_provider"),
            temperature=ConfigurableField(id="llm_temperature"),
            extra_body=ConfigurableField(id="llm_extra_body"),
        )
    return init_chat_model(
        profile.model,
        model_provider=profile.model_provider,
        temperature=profile.temperature,
        api_key=connection.api_key,
        base_url=connection.base_url,
        configurable_fields=("model", "model_provider", "temperature"),
        config_prefix="llm",
    )
