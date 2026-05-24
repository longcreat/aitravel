"""结构化卡片提取器注册表。

将 MCP / 本地工具返回的原始 payload 转换为类型化的 :class:`StructuredCard`,
方便前端按 ``card_type`` 注册渲染器,而不需要再做 payload 探测。

新增一种卡片类型(机票 / 行程 / POI / 订单 ...)只需要:

    1. 在本模块实现一个 :class:`CardExtractor` 子类(或直接当成 Protocol 实现)。
    2. 把它追加到 ``CARD_EXTRACTORS`` 列表。

不需要修改 ``streaming.py`` / 前端类型 / 数据流。前端只需为同一个 ``card_type``
注册对应渲染器即可。

设计原则:
    * 单条 payload 走完整条 extractors 链,谁先 ``matches`` 谁负责。
    * Extractor 永远不抛异常;遇到不识别的形状就返回空列表。
    * data 字段是 plain dict,不引入业务 model 在 schema 边界泄漏类型。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from app.schemas.chat import StructuredCard, ToolTrace


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class CardExtractor(Protocol):
    """一种卡片类型的提取器。"""

    card_type: str

    def matches(self, tool_name: str) -> bool:
        """该 extractor 是否适用于这个工具名。匹配规则属该领域的内部知识。"""
        ...

    def extract(self, payload: Any) -> list[dict[str, Any]]:
        """从 payload 中拆出 N 条卡片数据(每条是一个 ``card.data`` 字典)。"""
        ...


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _ensure_parsed(payload: Any) -> Any:
    """如果 payload 是 JSON 字符串就尝试解析,否则原样返回。"""
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                return None
        return None
    return payload


def _unwrap_mcp_text_blocks(payload: Any) -> Any:
    """递归解开 MCP ``{"type": "text", "text": "<json>"}`` 包装。

    很多 MCP server(包括 RollingGo 这类没声明 ``structured_content`` 的工具)
    通过 ``CallToolResult.content`` 返回 ``TextContent`` 列表,真正的结构化数据
    被序列化成 JSON 字符串塞进 ``text`` 字段。该助手把这种包装层剥掉,直到拿到
    第一层结构化数据。

    解包策略:
        * payload 是 list 且全部元素是 ``{type: "text", text: "<json>"}`` —
          逐项解析 ``text`` 中的 JSON,把结果合并(若 JSON 是 list 则 extend,
          若是 dict 则 wrap 进单元素 list)。
        * payload 是单条 ``{type: "text", text: ...}`` — 解析 ``text``。
        * 其它情况原样返回。
    """
    if isinstance(payload, list):
        unwrapped: list[Any] = []
        is_pure_text_blocks = True
        for item in payload:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                parsed_inner = _ensure_parsed(item["text"])
                if isinstance(parsed_inner, list):
                    unwrapped.extend(parsed_inner)
                elif parsed_inner is not None:
                    unwrapped.append(parsed_inner)
            else:
                is_pure_text_blocks = False
                break
        if is_pure_text_blocks and unwrapped:
            return unwrapped
        return payload
    if (
        isinstance(payload, dict)
        and payload.get("type") == "text"
        and isinstance(payload.get("text"), str)
    ):
        parsed_inner = _ensure_parsed(payload["text"])
        return parsed_inner if parsed_inner is not None else payload
    return payload


def _walk_lists(value: Any, max_depth: int = 2) -> Iterable[list[Any]]:
    """遍历 dict 内的 list 字段,最多向下穿透 ``max_depth`` 层。

    用于挖出形如 ``{ structured_content: { hotelInformationList: [...] } }``
    这种典型的 MCP 工具嵌套返回值。
    """
    if isinstance(value, list):
        yield value
        return
    if not isinstance(value, dict) or max_depth <= 0:
        return
    for nested in value.values():
        yield from _walk_lists(nested, max_depth - 1)


# ---------------------------------------------------------------------------
# Hotel extractor (RollingGo 主格式 + 通用酒店字段)
# ---------------------------------------------------------------------------


def _is_hotel_like(item: Any) -> bool:
    """宽松判断一个 dict 是否像一条酒店数据。

    要求至少有名称字段 + 至少一个酒店特征字段(价格/评分/地址/星级)。
    """
    if not isinstance(item, dict):
        return False
    has_name = any(
        isinstance(item.get(key), str) and item[key].strip()
        for key in ("name", "hotelName", "hotel_name")
    )
    if not has_name:
        return False
    has_price = (
        any(
            isinstance(item.get(key), (int, float)) and item[key] != 0
            for key in ("price", "pricePerNight", "price_per_night", "lowestPrice", "lowest_price")
        )
        # rollinggo: price: { lowestPrice: number, currency: str, ... }
        or (
            isinstance(item.get("price"), dict)
            and isinstance(item["price"].get("lowestPrice"), (int, float))
        )
    )
    has_rating = isinstance(item.get("rating"), (int, float)) or isinstance(item.get("score"), (int, float))
    has_address = isinstance(item.get("address"), str) or isinstance(item.get("location"), str)
    has_star = any(
        isinstance(item.get(key), (int, float))
        for key in ("star", "starLevel", "star_level", "starRating", "star_rating")
    )
    return has_price or has_rating or has_address or has_star


def _extract_hotel_price(raw: dict[str, Any]) -> dict[str, Any]:
    """从原始酒店字段中提炼价格:返回 price/unit/unavailable 子集。"""
    for key in ("price", "pricePerNight", "price_per_night", "lowestPrice", "lowest_price"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value != 0:
            return {"price": float(value)}
    price_obj = raw.get("price")
    if isinstance(price_obj, dict):
        lowest = price_obj.get("lowestPrice", price_obj.get("lowest_price"))
        currency = price_obj.get("currency") if isinstance(price_obj.get("currency"), str) else None
        if isinstance(lowest, (int, float)) and lowest > 0:
            result: dict[str, Any] = {"price": float(lowest)}
            if currency:
                result["price_unit"] = currency
            return result
        if price_obj.get("hasPrice") is False:
            message = price_obj.get("message")
            return {
                "price_unavailable": (
                    message.strip() if isinstance(message, str) and message.strip() else "暂未开放"
                )
            }
    return {}


def _normalize_hotel(raw: dict[str, Any]) -> dict[str, Any]:
    """把酒店原始字段归一化为前端 ``HotelItem`` data 字典。

    字段命名采用 snake_case_or_camelCase 双兼容,前端类型已声明小驼峰版本——
    我们这里输出小驼峰以与既有前端 ``HotelItem`` 接口保持一致。
    """
    price_fields = _extract_hotel_price(raw)

    def _str(*keys: str) -> str:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value:
                return value
            # ID-like fields can be int (RollingGo's hotelId is numeric)
            if isinstance(value, (int, float)) and value:
                return str(value)
        return ""

    def _opt_str(*keys: str) -> str | None:
        result = _str(*keys)
        return result or None

    def _opt_num(*keys: str) -> float | None:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)) and value:
                return float(value)
        return None

    tags_raw = raw.get("tags")
    tags = (
        [str(item) for item in tags_raw if str(item).strip()]
        if isinstance(tags_raw, list)
        else None
    )

    return {
        "id": _str("id", "hotelId", "hotel_id"),
        "name": _str("name", "hotelName", "hotel_name"),
        "brand": _opt_str("brand"),
        "address": _str("address", "location"),
        "price": price_fields.get("price"),
        "priceUnit": price_fields.get("price_unit")
        or _opt_str("priceUnit", "price_unit", "currency")
        or "CNY",
        "priceUnavailable": price_fields.get("price_unavailable"),
        "rating": _opt_num("rating", "score"),
        "star": _opt_num("star", "starLevel", "star_level", "starRating", "star_rating"),
        "imageUrl": _opt_str("imageUrl", "image_url", "image", "coverImage", "cover_image", "img"),
        "bookingUrl": _opt_str("bookingUrl", "booking_url"),
        "tags": tags,
        "checkIn": _opt_str("checkIn", "check_in"),
        "checkOut": _opt_str("checkOut", "check_out"),
        "roomType": _opt_str("roomType", "room_type"),
        "breakfast": _opt_str("breakfast"),
    }


class HotelCardExtractor:
    """酒店列表卡片提取器。"""

    card_type = "hotel"

    def matches(self, tool_name: str) -> bool:
        return "hotel" in tool_name.lower()

    def extract(self, payload: Any) -> list[dict[str, Any]]:
        # 先按需解 JSON 字符串(纯字符串 payload),再剥掉 MCP TextContent 包装层。
        if isinstance(payload, str):
            parsed: Any = _ensure_parsed(payload)
        else:
            parsed = payload
        parsed = _unwrap_mcp_text_blocks(parsed)
        if parsed is None:
            return []

        # 形状 A:直接 list[dict]
        if isinstance(parsed, list):
            hotels = [_normalize_hotel(item) for item in parsed if _is_hotel_like(item)]
            if hotels:
                return hotels
            # list 里也可能嵌套 list / dict(unwrap 后),再往下挖一层
            for item in parsed:
                if isinstance(item, dict):
                    if _is_hotel_like(item):
                        hotels.append(_normalize_hotel(item))
                        continue
                    for candidate in _walk_lists(item, max_depth=2):
                        nested = [
                            _normalize_hotel(child)
                            for child in candidate
                            if _is_hotel_like(child)
                        ]
                        if nested:
                            return nested
            return hotels

        # 形状 B:dict 内有 list 字段
        if isinstance(parsed, dict):
            # 单条酒店 dict
            if _is_hotel_like(parsed):
                return [_normalize_hotel(parsed)]
            for candidate in _walk_lists(parsed, max_depth=2):
                hotels = [
                    _normalize_hotel(item) for item in candidate if _is_hotel_like(item)
                ]
                if hotels:
                    return hotels

        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# 已注册的提取器,顺序决定优先级。新增卡片类型在此追加即可。
CARD_EXTRACTORS: list[CardExtractor] = [
    HotelCardExtractor(),
    # 机票示例(待实现):FlightCardExtractor(),
    # 行程示例(待实现):ItineraryCardExtractor(),
    # POI 示例(待实现):PoiCardExtractor(),
]


def extract_cards_from_trace(trace: ToolTrace) -> list[StructuredCard]:
    """从一条 ToolTrace 中抽取所有结构化卡片。

    遵循"第一个 ``matches`` 命中的 extractor 接管"原则,避免一条工具结果
    被多种 extractor 同时识别造成重复渲染。
    """
    if trace.payload is None:
        return []
    for extractor in CARD_EXTRACTORS:
        if not extractor.matches(trace.tool_name):
            continue
        try:
            data_list = extractor.extract(trace.payload)
        except Exception:  # pragma: no cover - extractor 自身异常不应阻断主流程
            return []
        if not data_list:
            continue
        return [
            StructuredCard(
                id=f"{extractor.card_type}-{index + 1}",
                card_type=extractor.card_type,
                data=data,
                source_tool_call_id=trace.tool_call_id,
            )
            for index, data in enumerate(data_list)
        ]
    return []
