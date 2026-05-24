"""Tests for the structured card extractor registry."""

from __future__ import annotations

import json

from app.agent.cards import (
    CARD_EXTRACTORS,
    HotelCardExtractor,
    extract_cards_from_trace,
)
from app.schemas.chat import StructuredCard, ToolTrace


def _make_trace(tool_name: str, payload, *, tool_call_id: str = "call-1") -> ToolTrace:
    return ToolTrace(
        phase="returned",
        tool_name=tool_name,
        payload=payload,
        tool_call_id=tool_call_id,
        result_status="success",
    )


def test_hotel_extractor_picks_up_list_payload() -> None:
    extractor = HotelCardExtractor()
    payload = [
        {"hotelName": "桔子酒店", "price": {"hasPrice": True, "lowestPrice": 277, "currency": "CNY"}, "address": "东胜街1号", "starLevel": 3},
        {"hotelName": "海友酒店", "price": {"hasPrice": True, "lowestPrice": 292, "currency": "CNY"}, "location": "锦江区"},
    ]

    cards = extractor.extract(payload)

    assert len(cards) == 2
    assert cards[0]["name"] == "桔子酒店"
    assert cards[0]["price"] == 277.0
    assert cards[0]["priceUnit"] == "CNY"
    assert cards[0]["star"] == 3.0
    assert cards[1]["name"] == "海友酒店"
    assert cards[1]["address"] == "锦江区"


def test_hotel_extractor_walks_nested_structured_content() -> None:
    extractor = HotelCardExtractor()
    payload = {
        "structured_content": {
            "hotelInformationList": [
                {"hotelName": "希尔顿", "price": 1888, "rating": 4.7, "address": "上海"},
            ]
        }
    }

    cards = extractor.extract(payload)

    assert len(cards) == 1
    assert cards[0]["name"] == "希尔顿"
    assert cards[0]["price"] == 1888.0


def test_hotel_extractor_handles_sold_out() -> None:
    extractor = HotelCardExtractor()
    payload = [
        {
            "hotelName": "全季酒店",
            "address": "杭州西湖区",
            "price": {"hasPrice": False, "message": "今日售罄", "currency": "CNY"},
            "bookingUrl": "https://example.com/booking/1",
        }
    ]

    cards = extractor.extract(payload)

    assert len(cards) == 1
    assert cards[0]["price"] is None
    assert cards[0]["priceUnavailable"] == "今日售罄"
    assert cards[0]["bookingUrl"] == "https://example.com/booking/1"


def test_hotel_extractor_accepts_json_string_payload() -> None:
    extractor = HotelCardExtractor()
    payload = json.dumps([{"hotelName": "万豪", "price": 999, "address": "北京"}])

    cards = extractor.extract(payload)

    assert len(cards) == 1
    assert cards[0]["name"] == "万豪"


def test_hotel_extractor_ignores_non_hotel_dicts() -> None:
    extractor = HotelCardExtractor()
    cards = extractor.extract({"items": [{"foo": "bar"}, {"name": "无地址", "tags": []}]})
    assert cards == []


def test_hotel_extractor_does_not_match_unrelated_tools() -> None:
    extractor = HotelCardExtractor()
    assert extractor.matches("amap-mcp-server_maps_weather") is False
    assert extractor.matches("rollinggo-hotel_searchHotels") is True
    assert extractor.matches("HOTEL_search") is True


def test_extract_cards_from_trace_returns_structured_cards() -> None:
    trace = _make_trace(
        "rollinggo-hotel_searchHotels",
        [{"hotelName": "桔子酒店", "price": 277, "address": "成都"}],
    )

    cards = extract_cards_from_trace(trace)

    assert len(cards) == 1
    card = cards[0]
    assert isinstance(card, StructuredCard)
    assert card.card_type == "hotel"
    assert card.id == "hotel-1"
    assert card.source_tool_call_id == "call-1"
    assert card.data["name"] == "桔子酒店"
    assert card.data["price"] == 277.0


def test_extract_cards_from_trace_returns_empty_for_unmatched_tool() -> None:
    trace = _make_trace("get_current_time", {"timezone": "Asia/Shanghai"})
    assert extract_cards_from_trace(trace) == []


def test_extract_cards_from_trace_returns_empty_when_no_data() -> None:
    trace = _make_trace("rollinggo-hotel_searchHotels", {"hotels": []})
    assert extract_cards_from_trace(trace) == []


def test_card_extractors_registry_contains_hotel() -> None:
    types = {extractor.card_type for extractor in CARD_EXTRACTORS}
    assert "hotel" in types


def test_hotel_extractor_unwraps_mcp_text_content_blocks() -> None:
    """RollingGo 返回的 artifact 是 [{type: "text", text: "<json>"}],需要先剥包装层。"""
    extractor = HotelCardExtractor()
    inner_payload = json.dumps(
        {
            "message": None,
            "hotelInformationList": [
                {
                    "hotelId": 2961,
                    "name": "曼谷凯宾斯基",
                    "address": "991 Rama 1 Road",
                    "starRating": 5,
                    "price": {"hasPrice": True, "lowestPrice": 1800, "currency": "CNY"},
                    "bookingUrl": "https://rollinggo.cn/pages/hotel/detail/index?id=2961",
                },
                {
                    "hotelId": 2942,
                    "name": "盛泰乐中央世界",
                    "address": "999/99 Rama 1 Road",
                    "starRating": 5,
                    "price": {"hasPrice": True, "lowestPrice": 1137, "currency": "CNY"},
                    "bookingUrl": "https://rollinggo.cn/pages/hotel/detail/index?id=2942",
                },
            ],
        }
    )
    payload = [{"type": "text", "text": inner_payload}]

    cards = extractor.extract(payload)

    assert len(cards) == 2
    assert cards[0]["name"] == "曼谷凯宾斯基"
    assert cards[0]["id"] == "2961"  # 数值 hotelId 也应转成字符串 id
    assert cards[0]["price"] == 1800.0
    assert cards[0]["star"] == 5.0
    assert cards[0]["bookingUrl"].startswith("https://rollinggo.cn")
    assert cards[1]["name"] == "盛泰乐中央世界"


def test_hotel_extractor_unwraps_single_mcp_text_block() -> None:
    """单条 {type: "text", text: ...} 字典形式也要支持。"""
    extractor = HotelCardExtractor()
    payload = {
        "type": "text",
        "text": json.dumps([{"hotelName": "希尔顿", "price": 999, "address": "上海"}]),
    }

    cards = extractor.extract(payload)

    assert len(cards) == 1
    assert cards[0]["name"] == "希尔顿"
