from __future__ import annotations

from app.tool.local_tools import get_current_time, get_local_tools


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
