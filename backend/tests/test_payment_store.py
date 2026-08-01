"""支付 SQLite 存储测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.payment.store import DAILY_FREE_LIMIT, PaymentSQLiteStore


@pytest.fixture()
def store(tmp_path: Path) -> PaymentSQLiteStore:
    return PaymentSQLiteStore(tmp_path / "payment.db")


def test_create_and_get_order(store: PaymentSQLiteStore) -> None:
    store.create_order(
        out_trade_no="202608010001",
        user_id="user-1",
        package_id="standard",
        amount="19.90",
        quota=150,
    )
    order = store.get_order("202608010001")
    assert order is not None
    assert order["user_id"] == "user-1"
    assert order["amount"] == "19.90"
    assert order["quota"] == 150
    assert order["status"] == "PENDING"


def test_mark_order_paid(store: PaymentSQLiteStore) -> None:
    store.create_order("202608010002", "user-1", "trial", "9.90", 50)
    changed = store.mark_order_paid("202608010002", "2026-08-01T10:00:00")
    assert changed is True
    # 幂等：重复置 PAID 返回 False
    changed_again = store.mark_order_paid("202608010002", "2026-08-01T10:00:00")
    assert changed_again is False


def test_grant_quota(store: PaymentSQLiteStore) -> None:
    store.grant_quota("user-1", 50)
    store.grant_quota("user-1", 100)
    row = store.get_quota("user-1")
    assert row is not None
    assert row["remain_count"] == 150


def test_consume_quota_free_first(store: PaymentSQLiteStore) -> None:
    # 新用户当天第一次消费走免费额度
    ok, free_used, remain = store.consume_quota("user-1", "2026-08-01")
    assert ok is True
    assert free_used == 1
    assert remain == 0


def test_consume_quota_free_resets_daily(store: PaymentSQLiteStore) -> None:
    for _ in range(DAILY_FREE_LIMIT):
        ok, free_used, _remain = store.consume_quota("user-1", "2026-08-01")
        assert ok is True
    # 免费额度用尽后仍可用（此刻 remain=0 → 返回 False）
    ok, free_used, remain = store.consume_quota("user-1", "2026-08-01")
    assert ok is False
    assert free_used == DAILY_FREE_LIMIT
    assert remain == 0
    # 次日重置
    ok, free_used, _remain = store.consume_quota("user-1", "2026-08-02")
    assert ok is True
    assert free_used == 1


def test_consume_quota_uses_purchased_after_free(store: PaymentSQLiteStore) -> None:
    store.grant_quota("user-1", 5)
    for _ in range(DAILY_FREE_LIMIT):
        store.consume_quota("user-1", "2026-08-01")
    ok, _free_used, remain = store.consume_quota("user-1", "2026-08-01")
    assert ok is True
    assert remain == 4
