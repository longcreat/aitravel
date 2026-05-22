"""LLM 提供方与模型档位配置。

每个档位（标准 / 思考）在进程启动时实例化为一个独立的 ChatModel。运行时由
`model_selection_middleware` 通过 `request.override(model=...)` 选择实际使用的实例。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_qwq import ChatQwen


ChatModelProfileKind = Literal["standard", "thinking"]

# 温度档位的兜底值；模型名 / provider 没有任何兜底，必须从环境变量明确给出。
_DEFAULT_TEMPERATURE = "0.2"


class LLMConfigError(ValueError):
    """LLM 配置缺失或非法时抛出。

    继承自 ``ValueError``，以兼容 ``api/sessions.py`` / ``api/chat.py`` 已有的
    ``except ValueError`` 处理（无效 profile_key 仍然返回 400）。
    """


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
    """判断该档位是否需要走百炼/Qwen 兼容适配器。"""
    normalized_provider = _normalize_provider(profile.model_provider)
    if normalized_provider == "qwen":
        return True
    return (
        normalized_provider == "openai"
        and _is_dashscope_base_url(connection.base_url)
        and _is_qwen_model(profile.model)
    )


def load_llm_profile_registry() -> LLMProfileRegistry:
    """从环境变量读取当前可用模型档位。

    模型名与 provider 必须显式给出（``LLM_PROFILE_STANDARD_MODEL`` /
    ``LLM_PROFILE_STANDARD_PROVIDER``，可由 ``LLM_MODEL`` / ``LLM_MODEL_PROVIDER``
    托底）。如果两套都没配置就直接抛错，防止生产环境用错误的兜底模型悄无声息
    地连到一个不存在的 provider。
    """
    standard_model = _env("LLM_PROFILE_STANDARD_MODEL", _env("LLM_MODEL"))
    if not standard_model:
        raise LLMConfigError(
            "LLM_PROFILE_STANDARD_MODEL (or LLM_MODEL) is required but not set"
        )
    standard_provider = _env("LLM_PROFILE_STANDARD_PROVIDER", _env("LLM_MODEL_PROVIDER"))
    if not standard_provider:
        raise LLMConfigError(
            "LLM_PROFILE_STANDARD_PROVIDER (or LLM_MODEL_PROVIDER) is required but not set"
        )
    standard_temperature = float(
        _env("LLM_PROFILE_STANDARD_TEMPERATURE", _env("LLM_TEMPERATURE", _DEFAULT_TEMPERATURE))
        or _DEFAULT_TEMPERATURE
    )

    thinking_model = _env("LLM_PROFILE_THINKING_MODEL", standard_model)
    thinking_provider = _env("LLM_PROFILE_THINKING_PROVIDER", standard_provider)
    thinking_temperature = float(
        _env("LLM_PROFILE_THINKING_TEMPERATURE", _env("LLM_TEMPERATURE", _DEFAULT_TEMPERATURE))
        or _DEFAULT_TEMPERATURE
    )

    profiles = {
        "standard": LLMProfile(
            key="standard",
            label=_env("LLM_PROFILE_STANDARD_LABEL", "普通") or "普通",
            kind="standard",
            model=standard_model,
            model_provider=standard_provider,
            temperature=standard_temperature,
        ),
        "thinking": LLMProfile(
            key="thinking",
            label=_env("LLM_PROFILE_THINKING_LABEL", "思考") or "思考",
            kind="thinking",
            model=thinking_model or standard_model,
            model_provider=thinking_provider or standard_provider,
            temperature=thinking_temperature,
        ),
    }

    default_profile_key = _env("LLM_PROFILE_DEFAULT", "standard") or "standard"
    if default_profile_key not in profiles:
        raise LLMConfigError(f"Invalid default LLM profile key: {default_profile_key}")

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
        raise LLMConfigError("Invalid model profile key")
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


def _profile_enable_thinking(profile: LLMProfile) -> bool | None:
    """决定 ChatQwen.enable_thinking 该传什么。

    - QwQ / 名字带 "thinking" 的纯思考模型：返回 None，让 SDK 走默认（不传字段）
    - 其它 Qwen 系列（Qwen3 / Qwen-Plus / Qwen-Max 等混合思考模型）：根据档位
      kind 显式传 True/False
    """
    normalized = profile.model.strip().lower()
    if normalized.startswith("qwq") or "thinking" in normalized:
        return None
    return profile.kind == "thinking"


def build_chat_model_for_profile(profile_key: str) -> BaseChatModel:
    """为指定档位实例化一个 ChatModel。

    各档位独立实例化，所有运行时差异（model 名、temperature、enable_thinking）
    都在实例化时固化。运行时由 `ModelSelectionMiddleware` 通过
    `request.override(model=...)` 在不同档位间切换。
    """
    profile = get_llm_profile(profile_key)
    connection = load_llm_connection_settings()
    if _uses_qwen_chat_adapter(profile, connection):
        kwargs: dict[str, object] = {
            "model": profile.model,
            "temperature": profile.temperature,
            "api_key": connection.api_key,
            "api_base": connection.base_url,
        }
        enable_thinking = _profile_enable_thinking(profile)
        if enable_thinking is not None:
            kwargs["enable_thinking"] = enable_thinking
        return ChatQwen(**kwargs)
    return init_chat_model(
        profile.model,
        model_provider=profile.model_provider,
        temperature=profile.temperature,
        api_key=connection.api_key,
        base_url=connection.base_url,
    )


def build_chat_models_by_profile() -> dict[str, BaseChatModel]:
    """为所有已注册档位预先构建 ChatModel 实例，供 middleware 在运行时按需选择。"""
    registry = load_llm_profile_registry()
    return {key: build_chat_model_for_profile(key) for key in registry.profiles}
