"""本地工具定义。

这些工具会与 MCP 工具一起注册到 Agent，作为模型可调用的函数集。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentRequestContext

@tool
def get_current_time(timezone_name: str = "Asia/Shanghai", runtime: ToolRuntime[AgentRequestContext] = None) -> dict:
    """返回指定时区的当前时间，默认使用上海时区。"""
    if timezone_name == "Asia/Shanghai" and runtime is not None and runtime.context.session_meta:
        context_timezone = runtime.context.session_meta.get("timezone")
        if isinstance(context_timezone, str) and context_timezone.strip():
            timezone_name = context_timezone.strip()

    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        fallback_timezones = {
            "Asia/Shanghai": dt_timezone(timedelta(hours=8), name="Asia/Shanghai"),
            "UTC": dt_timezone.utc,
        }
        tzinfo = fallback_timezones.get(timezone_name)
    if tzinfo is None:
        return {
            "error": f"Unknown timezone: {timezone_name}",
            "timezone": timezone_name,
        }

    now = datetime.now(tzinfo)
    return {
        "timezone": timezone_name,
        "iso_datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "utc_offset": now.strftime("%z"),
    }


def get_local_tools() -> list:
    """返回本地工具列表。"""
    return [get_current_time]
