from __future__ import annotations

import pytest

from app.tool.local_tools import get_current_time, get_local_tools, request_user_clarification


def test_get_current_time_returns_expected_fields() -> None:
    result = get_current_time.invoke({})

    assert result["timezone"] == "Asia/Shanghai"
    assert "iso_datetime" in result
    assert "date" in result
    assert "time" in result
    assert "weekday" in result
    assert "utc_offset" in result


def test_get_local_tools_includes_time_tool() -> None:
    tool_names = [tool.name for tool in get_local_tools()]

    assert "get_current_time" in tool_names
    assert "request_user_clarification" in tool_names
    assert "exa_web_search_advanced_exa" in tool_names
    assert "exa_web_fetch_exa" in tool_names


def test_request_user_clarification_interrupts_with_normalized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payload: dict | None = None

    def _fake_interrupt(payload: dict) -> str:
        nonlocal captured_payload
        captured_payload = payload
        return "杭州"

    monkeypatch.setattr("app.tool.local_tools.interrupt", _fake_interrupt)

    result = request_user_clarification.invoke(
        {
            "question": "  请问你想查哪个城市的天气？  ",
            "missing_field": " city ",
            "suggested_replies": [" 杭州 ", "上海", "   "],
        }
    )

    assert result == "杭州"
    assert captured_payload == {
        "kind": "clarification",
        "question": "请问你想查哪个城市的天气？",
        "missing_field": "city",
        "suggested_replies": ["杭州", "上海"],
        "allow_custom_input": True,
    }
