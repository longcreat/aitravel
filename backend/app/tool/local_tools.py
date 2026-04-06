"""本地工具定义。

这些工具会与 MCP 工具一起注册到 Agent，作为模型可调用的函数集。
"""

from __future__ import annotations

from typing import Literal

from langchain.tools import tool


@tool
def estimate_trip_budget(
    days: int, travelers: int, budget_level: Literal["economy", "standard", "premium"] = "standard"
) -> dict:
    """根据天数、人数与预算等级估算总预算（人民币）。"""
    level_multiplier = {"economy": 0.75, "standard": 1.0, "premium": 1.8}
    base_cost_per_day = 900
    total = int(days * travelers * base_cost_per_day * level_multiplier[budget_level])
    return {
        "currency": "CNY",
        "total_estimate": total,
        "daily_per_person": int(total / max(days * travelers, 1)),
        "assumption": f"{budget_level} level with typical city travel costs",
    }


@tool
def convert_currency(amount: float, from_currency: str, to_currency: str, fx_rate: float) -> dict:
    """按传入汇率执行币种换算。"""
    converted = round(amount * fx_rate, 2)
    return {
        "from": {"currency": from_currency.upper(), "amount": amount},
        "to": {"currency": to_currency.upper(), "amount": converted},
        "fx_rate": fx_rate,
    }


@tool
def suggest_city_by_theme(theme: str, season: str = "all") -> dict:
    """根据旅行主题与季节偏好推荐候选城市。"""
    mapping = {
        "culture": ["Kyoto", "Istanbul", "Xi'an"],
        "food": ["Osaka", "Bangkok", "Chengdu"],
        "nature": ["Reykjavik", "Queenstown", "Yunnan"],
        "beach": ["Phuket", "Bali", "Sanya"],
    }
    normalized = theme.strip().lower()
    return {
        "theme": normalized,
        "season": season,
        "cities": mapping.get(normalized, ["Tokyo", "Singapore", "Shanghai"]),
    }


def get_local_tools() -> list:
    """返回本地工具列表。"""
    return [estimate_trip_budget, convert_currency, suggest_city_by_theme]
