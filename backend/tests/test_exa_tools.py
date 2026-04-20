from __future__ import annotations

import pytest

from app.tool.exa_tools import (
    ExaRequestError,
    _run_exa_web_fetch_exa,
    _run_exa_web_search_advanced_exa,
)


@pytest.mark.asyncio
async def test_run_exa_web_search_advanced_exa_maps_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    captured: dict[str, object] = {}

    async def _fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured["path"] = path
        captured["payload"] = payload
        return {
            "requestId": "req-search-1",
            "searchType": "deep",
            "results": [
                {
                    "title": "Official Travel Guide",
                    "url": "https://example.com/guide",
                    "id": "doc-1",
                    "publishedDate": "2026-04-20T00:00:00Z",
                    "author": "Travel Team",
                    "image": "https://example.com/cover.png",
                    "favicon": "https://example.com/favicon.ico",
                    "highlights": ["Top attraction"],
                    "highlightScores": [0.98],
                    "summary": "Short summary",
                    "text": "Long markdown",
                    "extras": {"links": ["https://example.com/related"]},
                    "subpages": [
                        {
                            "title": "Subpage",
                            "url": "https://example.com/subpage",
                            "id": "doc-sub-1",
                            "highlights": ["Nested highlight"],
                        }
                    ],
                }
            ],
            "costDollars": {"total": 0.012},
        }

    monkeypatch.setattr("app.tool.exa_tools._request_exa_json", _fake_request)

    message = await _run_exa_web_search_advanced_exa(
        query="东京自由行攻略",
        num_results=3,
        tool_call_id="call-search-1",
    )

    assert captured["path"] == "/search"
    assert captured["payload"] == {
        "query": "东京自由行攻略",
        "type": "deep",
        "numResults": 3,
        "contents": {
            "highlights": {"maxCharacters": 1200},
            "summary": {},
        },
    }
    assert message.status == "success"
    assert message.tool_call_id == "call-search-1"
    assert message.name == "exa_web_search_advanced_exa"
    assert "Exa 高级搜索找到 1 条结果" in str(message.content)
    assert message.artifact == {
        "requestId": "req-search-1",
        "searchType": "deep",
        "results": [
            {
                "title": "Official Travel Guide",
                "url": "https://example.com/guide",
                "id": "doc-1",
                "publishedDate": "2026-04-20T00:00:00Z",
                "author": "Travel Team",
                "image": "https://example.com/cover.png",
                "favicon": "https://example.com/favicon.ico",
                "highlights": ["Top attraction"],
                "highlightScores": [0.98],
                "summary": "Short summary",
                "text": "Long markdown",
                "extras": {"links": ["https://example.com/related"]},
                "subpages": [
                    {
                        "title": "Subpage",
                        "url": "https://example.com/subpage",
                        "id": "doc-sub-1",
                        "highlights": ["Nested highlight"],
                    }
                ],
            }
        ],
        "costDollars": {"total": 0.012},
    }


@pytest.mark.asyncio
async def test_run_exa_web_fetch_exa_maps_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    captured: dict[str, object] = {}

    async def _fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured["path"] = path
        captured["payload"] = payload
        return {
            "requestId": "req-contents-1",
            "results": [
                {
                    "title": "Kyoto Travel Notes",
                    "url": "https://example.com/kyoto",
                    "id": "doc-2",
                    "text": "Useful full text",
                    "highlights": ["Best season is spring"],
                    "highlightScores": [0.76],
                    "summary": "Useful summary",
                    "extras": {"links": ["https://example.com/more"]},
                }
            ],
            "statuses": [{"id": "doc-2", "status": "success", "error": None}],
            "costDollars": {"total": 0.001},
        }

    monkeypatch.setattr("app.tool.exa_tools._request_exa_json", _fake_request)

    message = await _run_exa_web_fetch_exa(
        urls=[" https://example.com/kyoto ", ""],
        tool_call_id="call-contents-1",
    )

    assert captured["path"] == "/contents"
    assert captured["payload"] == {
        "urls": ["https://example.com/kyoto"],
        "text": True,
        "highlights": {"maxCharacters": 1200},
        "summary": {},
    }
    assert message.status == "success"
    assert message.tool_call_id == "call-contents-1"
    assert message.name == "exa_web_fetch_exa"
    assert "Exa 已抓取 1 个页面" in str(message.content)
    assert message.artifact == {
        "requestId": "req-contents-1",
        "results": [
            {
                "title": "Kyoto Travel Notes",
                "url": "https://example.com/kyoto",
                "id": "doc-2",
                "text": "Useful full text",
                "highlights": ["Best season is spring"],
                "highlightScores": [0.76],
                "summary": "Useful summary",
                "extras": {"links": ["https://example.com/more"]},
            }
        ],
        "statuses": [{"id": "doc-2", "status": "success", "error": None}],
        "costDollars": {"total": 0.001},
    }


@pytest.mark.asyncio
async def test_run_exa_tools_return_structured_error_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    search_message = await _run_exa_web_search_advanced_exa(
        query="大阪美食推荐",
        num_results=5,
        tool_call_id="call-search-error",
    )
    contents_message = await _run_exa_web_fetch_exa(
        urls=["https://example.com/osaka"],
        tool_call_id="call-contents-error",
    )

    assert search_message.status == "error"
    assert search_message.artifact == {"error": "缺少 EXA_API_KEY，无法调用 Exa API。"}

    assert contents_message.status == "error"
    assert contents_message.artifact == {"error": "缺少 EXA_API_KEY，无法调用 Exa API。"}


@pytest.mark.asyncio
async def test_run_exa_tools_return_structured_error_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")

    async def _fake_request(_path: str, _payload: dict[str, object]) -> dict[str, object]:
        raise ExaRequestError(
            "Unauthorized",
            status_code=401,
            raw={"error": "Unauthorized"},
        )

    monkeypatch.setattr("app.tool.exa_tools._request_exa_json", _fake_request)

    search_message = await _run_exa_web_search_advanced_exa(
        query="东京酒店",
        num_results=2,
        tool_call_id="call-search-http-error",
    )
    contents_message = await _run_exa_web_fetch_exa(
        urls=["https://example.com/tokyo"],
        tool_call_id="call-contents-http-error",
    )

    assert search_message.status == "error"
    assert search_message.artifact == {"error": "Unauthorized"}

    assert contents_message.status == "error"
    assert contents_message.artifact == {"error": "Unauthorized"}
