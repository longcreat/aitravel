"""Qwen OpenAI-compatible ChatOpenAI 适配。

该模块保留 LangChain / ChatOpenAI 的整体调用方式，只补齐百炼 OpenAI-compatible
接口在 Chat Completions 流式返回中的 `reasoning_content` 字段。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field


def _coerce_reasoning_content(value: Any) -> str | None:
    """把 provider 返回的 reasoning_content 归一化为字符串。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _attach_reasoning_content(message: Any, reasoning_content: Any) -> None:
    """把 reasoning_content 挂回 LangChain message.additional_kwargs。"""
    normalized = _coerce_reasoning_content(reasoning_content)
    if normalized in (None, ""):
        return
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return

    message.additional_kwargs = {
        **message.additional_kwargs,
        "reasoning_content": normalized,
    }


class PatchedQwenChatOpenAI(ChatOpenAI):
    """为百炼/Qwen 的 OpenAI-compatible Chat Completions 补齐思考字段。"""

    model_provider: str = Field(default="qwen")

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if choices:
            reasoning_content = (choices[0].get("delta") or {}).get("reasoning_content")
            _attach_reasoning_content(generation_chunk.message, reasoning_content)

        return generation_chunk

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()

        for generation, choice in zip(chat_result.generations, response_dict.get("choices", []), strict=False):
            reasoning_content = (choice.get("message") or {}).get("reasoning_content")
            _attach_reasoning_content(generation.message, reasoning_content)

        return chat_result
