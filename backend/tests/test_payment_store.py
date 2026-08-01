"""支付 SQLite 存储测试。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.auth.store import AuthSQLiteStore
from app.db.bootstrap import bootstrap_sqlite_database
from app.payment.store import DAILY_FREE_LIMIT, PaymentSQLiteStore


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return bootstrap_sqlite_database(tmp_path / "payment.db")


@pytest.fixture()
def user_id(db_path: Path) -> str:
    return AuthSQLiteStore(db_path).create_user("user-1@example.com").id


@pytest.fixture()
def store(db_path: Path) -> PaymentSQLiteStore:
    return PaymentSQLiteStore(db_path)


def test_create_and_get_order(store: PaymentSQLiteStore, user_id: str) -> None:
    store.create_order(
        out_trade_no="202608010001",
        user_id=user_id,
        package_id="standard",
        amount="19.90",
        quota=150,
    )
    order = store.get_order("202608010001")
    assert order is not None
    assert order["user_id"] == user_id
    assert order["amount"] == "19.90"
    assert order["quota"] == 150
    assert order["status"] == "PENDING"


def test_mark_order_paid(store: PaymentSQLiteStore, user_id: str) -> None:
    store.create_order("202608010002", user_id, "trial", "9.90", 50)
    changed = store.mark_order_paid("202608010002", "2026-08-01T10:00:00")
    assert changed is True
    # 幂等：重复置 PAID 返回 False
    changed_again = store.mark_order_paid("202608010002", "2026-08-01T10:00:00")
    assert changed_again is False


def test_mark_order_paid_nonexistent_order(store: PaymentSQLiteStore) -> None:
    assert store.mark_order_paid("no-such-order") is False


def test_mark_order_paid_does_not_flip_closed(
    store: PaymentSQLiteStore, user_id: str, db_path: Path
) -> None:
    store.create_order("202608010003", user_id, "trial", "9.90", 50)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE payment_orders SET status = 'CLOSED' WHERE out_trade_no = ?",
            ("202608010003",),
        )
        conn.commit()
    finally:
        conn.close()
    assert store.mark_order_paid("202608010003") is False
    order = store.get_order("202608010003")
    assert order is not None
    assert order["status"] == "CLOSED"


def test_grant_quota(store: PaymentSQLiteStore, user_id: str) -> None:
    store.grant_quota(user_id, 50)
    store.grant_quota(user_id, 100)
    row = store.get_quota(user_id)
    assert row is not None
    assert row["remain_count"] == 150


def test_mark_paid_and_grant(store: PaymentSQLiteStore, user_id: str) -> None:
    store.create_order("202608010004", user_id, "trial", "9.90", 50)
    changed = store.mark_paid_and_grant("202608010004", 50, "2026-08-01T10:00:00")
    assert changed is True
    order = store.get_order("202608010004")
    assert order is not None
    assert order["status"] == "PAID"
    row = store.get_quota(user_id)
    assert row is not None
    assert row["remain_count"] == 50
    # 幂等：重复调用返回 False 且只加一次
    changed_again = store.mark_paid_and_grant("202608010004", 50, "2026-08-01T10:00:00")
    assert changed_again is False
    row = store.get_quota(user_id)
    assert row is not None
    assert row["remain_count"] == 50


def test_mark_paid_and_grant_nonexistent_order(store: PaymentSQLiteStore) -> None:
    assert store.mark_paid_and_grant("no-such-order", 50) is False


def test_mark_paid_and_grant_accumulates_quota(store: PaymentSQLiteStore, user_id: str) -> None:
    store.grant_quota(user_id, 10)
    store.create_order("202608010005", user_id, "standard", "19.90", 150)
    assert store.mark_paid_and_grant("202608010005", 150) is True
    row = store.get_quota(user_id)
    assert row is not None
    assert row["remain_count"] == 160


def test_consume_quota_free_first(store: PaymentSQLiteStore, user_id: str) -> None:
    # 新用户当天第一次消费走免费额度
    ok, free_used, remain = store.consume_quota(user_id, "2026-08-01")
    assert ok is True
    assert free_used == 1
    assert remain == 0


def test_consume_quota_free_resets_daily(store: PaymentSQLiteStore, user_id: str) -> None:
    for _ in range(DAILY_FREE_LIMIT):
        ok, free_used, _remain = store.consume_quota(user_id, "2026-08-01")
        assert ok is True
    # 免费额度用尽后仍可用（此刻 remain=0 → 返回 False）
    ok, free_used, remain = store.consume_quota(user_id, "2026-08-01")
    assert ok is False
    assert free_used == DAILY_FREE_LIMIT
    assert remain == 0
    # 次日重置
    ok, free_used, _remain = store.consume_quota(user_id, "2026-08-02")
    assert ok is True
    assert free_used == 1


def test_consume_quota_uses_purchased_after_free(store: PaymentSQLiteStore, user_id: str) -> None:
    store.grant_quota(user_id, 5)
    for _ in range(DAILY_FREE_LIMIT):
        store.consume_quota(user_id, "2026-08-01")
    ok, _free_used, remain = store.consume_quota(user_id, "2026-08-01")
    assert ok is True
    assert remain == 4
