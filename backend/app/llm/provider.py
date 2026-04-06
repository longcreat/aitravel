"""LLM 提供方初始化逻辑。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from langchain_openai import ChatOpenAI


@dataclass(frozen=True)
class LLMSettings:
    """聊天模型配置。"""

    model: str
    temperature: float
    api_key: str | None
    base_url: str | None


def load_llm_settings() -> LLMSettings:
    """从环境变量读取 LLM 配置。

    说明：
    - 兼容 OpenAI 标准接口；
    - 也可通过 `OPENAI_BASE_URL` 对接 OpenAI 兼容供应商（如 Qwen 兼容网关）。
    """
    model = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    return LLMSettings(
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
    )


def build_chat_model() -> ChatOpenAI:
    """构建 LangChain `ChatOpenAI` 模型实例。"""
    settings = load_llm_settings()
    return ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
