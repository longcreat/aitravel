"""本地工具定义。

这些工具会与 MCP 工具一起注册到 Agent，作为模型可调用的函数集。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from app.agent.context import AgentRequestContext
from app.tool.exa_tools import exa_web_fetch_exa, exa_web_search_advanced_exa

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


@tool
def request_user_clarification(
    question: str,
    missing_field: str,
    suggested_replies: list[str] | None = None,
    runtime: ToolRuntime[AgentRequestContext] = None,
) -> str:
    """当关键信息缺失时，暂停当前执行并向用户补问。

    使用规则：
    - 只在你无法继续可靠规划、查询或调用工具时使用。
    - 这是向用户发起追问的唯一标准方式；不要直接输出自然语言追问。
    - 每次只追问一个最关键的缺失字段。
    - question 写成用户可直接回答的一句话。
    - missing_field 使用简洁字段名，例如 city / destination_city / date / travelers / budget。
    - suggested_replies 最多给 2 个简短可点选答案；如果没有合适选项，可留空。
    """
    del runtime  # 当前版本无需读取额外 runtime 数据。

    question = question.strip()
    missing_field = missing_field.strip()
    suggested_replies = [
        reply.strip()
        for reply in (suggested_replies or [])
        if isinstance(reply, str) and reply.strip()
    ][:2]

    answer = interrupt(
        {
            "kind": "clarification",
            "question": question,
            "missing_field": missing_field or None,
            "suggested_replies": suggested_replies,
            "allow_custom_input": True,
        }
    )
    return str(answer).strip()


def get_local_tools() -> list:
    """返回本地工具列表。"""
    return [
        get_current_time,
        request_user_clarification,
        exa_web_search_advanced_exa,
        exa_web_fetch_exa,
    ]
