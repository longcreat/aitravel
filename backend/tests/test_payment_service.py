"""支付服务测试（不触网，验签与加次数逻辑）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.payment.service import PACKAGES, QuotaExhaustedError, PaymentService
from app.payment.store import DAILY_FREE_LIMIT

INVALID_APP_ID = "9021000165642883"


class FakeStore:
    """按 store 接口的最小 fake：记录调用，允许注入行为。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self.orders: dict[str, dict] = {}
        self.quota: dict[str, dict] = {}
        self.paid_calls: list[str] = []
        self.grant_calls: list[tuple[str, int]] = []

    def create_order(self, **kwargs) -> None:
        self.orders[kwargs["out_trade_no"]] = dict(kwargs, status="PENDING")

    def get_order(self, out_trade_no: str) -> dict | None:
        return self.orders.get(out_trade_no)

    def mark_order_paid(self, out_trade_no: str, paid_at: str | None = None) -> bool:
        order = self.orders.get(out_trade_no)
        if order is None or order["status"] == "PAID":
            return False
        order["status"] = "PAID"
        self.paid_calls.append(out_trade_no)
        return True

    def mark_paid_and_grant(
        self,
        out_trade_no: str,
        count: int,
        trade_no: str | None = None,
        paid_at: str | None = None,
    ) -> bool:
        if not self.mark_order_paid(out_trade_no, paid_at):
            return False
        self.orders[out_trade_no]["trade_no"] = trade_no
        self.grant_quota(str(self.orders[out_trade_no]["user_id"]), count)
        return True

    def get_quota(self, user_id: str) -> dict | None:
        return self.quota.setdefault(user_id, {"remain_count": 0, "free_date": "", "free_used": 0})

    def grant_quota(self, user_id: str, count: int) -> None:
        self.grant_calls.append((user_id, count))

    def consume_quota(self, user_id: str, today: str) -> tuple[bool, int, int]:
        row = self.get_quota(user_id)
        if row["free_used"] < DAILY_FREE_LIMIT:
            row["free_used"] += 1
            return True, row["free_used"], row["remain_count"]
        if row["remain_count"] > 0:
            row["remain_count"] -= 1
            return True, row["free_used"], row["remain_count"]
        return False, row["free_used"], row["remain_count"]


@pytest.fixture()
def service(tmp_path: Path) -> PaymentService:
    return PaymentService(sqlite_db_path=tmp_path / "payment.db", store_cls=FakeStore)


def test_create_payment_order_uses_package(service: PaymentService) -> None:
    out_trade_no = service.create_payment_order(user_id="user-1", package_id="standard")
    order = service._store.orders[out_trade_no]
    assert order["amount"] == "19.90"
    assert order["quota"] == 150
    assert order["user_id"] == "user-1"
    assert order["status"] == "PENDING"


def test_create_payment_order_rejects_unknown_package(service: PaymentService) -> None:
    with pytest.raises(HTTPException):
        service.create_payment_order(user_id="user-1", package_id="nope")


def test_get_subscription_shape(service: PaymentService) -> None:
    subscription = service.get_subscription("user-1")
    assert subscription["daily_free_limit"] == 10
    assert subscription["remain_count"] == 0
    assert {p["id"] for p in subscription["packages"]} == set(PACKAGES)


def test_consume_raises_when_exhausted(service: PaymentService) -> None:
    for _ in range(10):
        service.consume("user-1")
    with pytest.raises(QuotaExhaustedError):
        service.consume("user-1")


def test_consume_returns_progression(service: PaymentService) -> None:
    for expected_free_used in range(1, DAILY_FREE_LIMIT + 1):
        free_used, remain = service.consume("user-1")
        assert free_used == expected_free_used
        assert remain == 0


def test_get_subscription_free_reset(service: PaymentService) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    service._store.quota["user-1"] = {"remain_count": 0, "free_date": today, "free_used": 3}
    subscription = service.get_subscription("user-1")
    assert subscription["free_used"] == 3

    service._store.quota["user-1"] = {"remain_count": 5, "free_date": yesterday, "free_used": 9}
    subscription = service.get_subscription("user-1")
    assert subscription["free_used"] == 0
    assert subscription["remain_count"] == 5


def test_handle_notify_invalid_signature_fails(service: PaymentService) -> None:
    data = {"out_trade_no": "n1", "total_amount": "9.90", "trade_status": "TRADE_SUCCESS", "app_id": INVALID_APP_ID}
    assert service.handle_notify(data, "bad-sign") is False
    assert service._store.paid_calls == []


def test_handle_notify_wrong_app_id_fails(service: PaymentService) -> None:
    data = {
        "out_trade_no": "n1",
        "total_amount": "9.90",
        "trade_status": "TRADE_SUCCESS",
        "app_id": "1111111111111111",
    }
    # 验签必然失败（无真实公钥），断言整体 False 且未加次数
    assert service.handle_notify(data, "sign") is False
    assert service._store.grant_calls == []


def test_handle_notify_amount_mismatch_fails(service: PaymentService) -> None:
    service.create_payment_order(user_id="user-1", package_id="trial")
    out_trade_no = next(iter(service._store.orders))
    data = {
        "out_trade_no": out_trade_no,
        "total_amount": "0.01",
        "trade_status": "TRADE_SUCCESS",
        "app_id": INVALID_APP_ID,
    }
    assert service.handle_notify(data, "sign") is False
    assert service._store.paid_calls == []
    assert service._store.grant_calls == []
