"""支付相关 SQLite 存储。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DAILY_FREE_LIMIT = 10


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaymentSQLiteStore:
    """支付订单与用户次数额度的 SQLite 存储。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 订单 ----

    def create_order(
        self,
        out_trade_no: str,
        user_id: str,
        package_id: str,
        amount: str,
        quota: int,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO payment_orders
                  (out_trade_no, user_id, package_id, amount, quota, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (out_trade_no, user_id, package_id, amount, quota, _utc_now_iso()),
            )

    def get_order(self, out_trade_no: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def mark_order_paid(self, out_trade_no: str, paid_at: str | None = None) -> bool:
        """将订单置为 PAID；非 PENDING 状态或不存在时返回 False。

        单条条件 UPDATE 保证原子性：并发回调下只有一个成功，
        避免重复发放额度。已 PAID / CLOSED / REFUNDED 均不会被翻转。
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE payment_orders
                SET status = 'PAID', paid_at = ?
                WHERE out_trade_no = ? AND status = 'PENDING'
                """,
                (paid_at or _utc_now_iso(), out_trade_no),
            )
            return cursor.rowcount == 1

    def mark_paid_and_grant(self, out_trade_no: str, count: int, paid_at: str | None = None) -> bool:
        """原子完成：PENDING→PAID 并给 user 加次数；失败/已处理返回 False。"""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,),
            ).fetchone()
            if row is None:
                return False
            cursor = conn.execute(
                """
                UPDATE payment_orders
                SET status = 'PAID', paid_at = ?
                WHERE out_trade_no = ? AND status = 'PENDING'
                """,
                (paid_at or _utc_now_iso(), out_trade_no),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                """
                INSERT INTO user_quota (user_id, remain_count, free_date, free_used)
                VALUES (?, ?, '', 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    remain_count = remain_count + excluded.remain_count
                """,
                (str(row["user_id"]), count),
            )
            return True

    # ---- 额度 ----

    def _ensure_quota_row(self, conn: sqlite3.Connection, user_id: str) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_quota (user_id, remain_count, free_date, free_used)
            VALUES (?, 0, '', 0)
            """,
            (user_id,),
        )

    def get_quota(self, user_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            self._ensure_quota_row(conn, user_id)
            row = conn.execute(
                "SELECT remain_count, free_date, free_used FROM user_quota WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def grant_quota(self, user_id: str, count: int) -> None:
        with self._connection() as conn:
            self._ensure_quota_row(conn, user_id)
            conn.execute(
                "UPDATE user_quota SET remain_count = remain_count + ? WHERE user_id = ?",
                (count, user_id),
            )

    def consume_quota(self, user_id: str, today: str) -> tuple[bool, int, int]:
        """消费 1 次：先免费后购买额度。

        返回 (是否成功, 更新后的 free_used, 更新后的 remain_count)。
        """
        with self._connection() as conn:
            self._ensure_quota_row(conn, user_id)
            row = conn.execute(
                "SELECT remain_count, free_date, free_used FROM user_quota WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            free_used = 0 if str(row["free_date"]) != today else int(row["free_used"])
            remain = int(row["remain_count"])
            if free_used < DAILY_FREE_LIMIT:
                conn.execute(
                    "UPDATE user_quota SET free_used = ?, free_date = ? WHERE user_id = ?",
                    (free_used + 1, today, user_id),
                )
                return True, free_used + 1, remain
            if remain > 0:
                conn.execute(
                    "UPDATE user_quota SET remain_count = ? WHERE user_id = ?",
                    (remain - 1, user_id),
                )
                return True, free_used, remain - 1
            return False, free_used, remain
