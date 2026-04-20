"""Exa API 本地工具。"""

from __future__ import annotations

import os
from typing import Annotated, Any

import httpx
from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from pydantic import Field


_EXA_BASE_URL = "https://api.exa.ai"


class ExaRequestError(Exception):
    """Exa API 请求失败。"""

    def __init__(self, message: str, *, status_code: int | None = None, raw: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


def _exa_api_key() -> str:
    return os.getenv("EXA_API_KEY", "").strip()


def _extract_error_message(raw: Any, fallback: str) -> str:
    if isinstance(raw, dict):
        for key in ("error", "message", "detail"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return fallback


async def _request_exa_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = _exa_api_key()
    if not api_key:
        raise ExaRequestError("缺少 EXA_API_KEY，无法调用 Exa API。")

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(base_url=_EXA_BASE_URL, timeout=30.0) as client:
            response = await client.post(path, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raw: Any
        try:
            raw = exc.response.json()
        except ValueError:
            raw = exc.response.text
        raise ExaRequestError(
            _extract_error_message(raw, f"Exa API 返回 HTTP {exc.response.status_code}。"),
            status_code=exc.response.status_code,
            raw=raw,
        ) from exc
    except httpx.HTTPError as exc:
        raise ExaRequestError(f"请求 Exa API 失败：{exc}") from exc


def _build_error_artifact(message: str, raw: Any = None) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        return {"error": raw.strip()}
    return {"error": message}


def _response_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in response.get("results") or [] if isinstance(item, dict)]


def _build_search_content(query: str, response: dict[str, Any]) -> str:
    results = _response_results(response)
    if not results:
        return f"Exa 高级搜索未找到与“{query}”相关的结果。"

    lines = [f"Exa 高级搜索找到 {len(results)} 条结果。"]
    for index, item in enumerate(results[:3], start=1):
        title = str(item.get("title") or item.get("url") or f"结果 {index}").strip()
        lines.append(f"{index}. {title}")
    return "\n".join(lines)


def _build_contents_content(response: dict[str, Any]) -> str:
    results = _response_results(response)
    if not results:
        return "Exa 内容抓取没有返回可用页面。"

    lines = [f"Exa 已抓取 {len(results)} 个页面。"]
    for index, item in enumerate(results[:3], start=1):
        title = str(item.get("title") or item.get("url") or f"页面 {index}").strip()
        lines.append(f"{index}. {title}")
    return "\n".join(lines)


async def _run_exa_web_search_advanced_exa(
    *,
    query: str,
    num_results: int,
    tool_call_id: str,
) -> ToolMessage:
    payload = {
        "query": query,
        "type": "deep",
        "numResults": num_results,
        "contents": {
            "highlights": {
                "maxCharacters": 1200,
            },
            "summary": {},
        },
    }

    try:
        response = await _request_exa_json("/search", payload)
    except ExaRequestError as exc:
        return ToolMessage(
            content=f"Exa 高级搜索失败：{exc}",
            artifact=_build_error_artifact(str(exc), exc.raw),
            tool_call_id=tool_call_id,
            name="exa_web_search_advanced_exa",
            status="error",
        )

    return ToolMessage(
        content=_build_search_content(query, response),
        artifact=response,
        tool_call_id=tool_call_id,
        name="exa_web_search_advanced_exa",
        status="success",
    )


async def _run_exa_web_fetch_exa(
    *,
    urls: list[str],
    tool_call_id: str,
) -> ToolMessage:
    normalized_urls = [url.strip() for url in urls if isinstance(url, str) and url.strip()]
    if not normalized_urls:
        return ToolMessage(
            content="Exa 内容抓取失败：urls 不能为空。",
            artifact={"error": "urls 不能为空。"},
            tool_call_id=tool_call_id,
            name="exa_web_fetch_exa",
            status="error",
        )

    payload = {
        "urls": normalized_urls,
        "text": True,
        "highlights": {
            "maxCharacters": 1200,
        },
        "summary": {},
    }

    try:
        response = await _request_exa_json("/contents", payload)
    except ExaRequestError as exc:
        return ToolMessage(
            content=f"Exa 内容抓取失败：{exc}",
            artifact=_build_error_artifact(str(exc), exc.raw),
            tool_call_id=tool_call_id,
            name="exa_web_fetch_exa",
            status="error",
        )

    return ToolMessage(
        content=_build_contents_content(response),
        artifact=response,
        tool_call_id=tool_call_id,
        name="exa_web_fetch_exa",
        status="success",
    )


@tool
async def exa_web_search_advanced_exa(
    query: str,
    num_results: Annotated[int, Field(ge=1, le=10)] = 5,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> ToolMessage:
    """使用 Exa Deep Search 搜索网页，并返回 Exa 原始 JSON 结果。"""

    return await _run_exa_web_search_advanced_exa(
        query=query,
        num_results=num_results,
        tool_call_id=tool_call_id,
    )


@tool
async def exa_web_fetch_exa(
    urls: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> ToolMessage:
    """抓取指定网页内容，并返回 Exa 原始 JSON 结果。"""

    return await _run_exa_web_fetch_exa(
        urls=urls,
        tool_call_id=tool_call_id,
    )
