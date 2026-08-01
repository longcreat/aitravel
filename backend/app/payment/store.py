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
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """确保两张表存在（生产环境由 migration 007 建表，此处幂等补建）。

        注意：此处不声明外键，测试使用临时 DB 与任意 user_id；
        生产库的表由 migration 007 创建，外键约束仍生效。
        """
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_orders (
                  out_trade_no TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  package_id TEXT NOT NULL,
                  amount TEXT NOT NULL,
                  quota INTEGER NOT NULL,
                  status TEXT NOT NULL DEFAULT 'PENDING',
                  created_at TEXT NOT NULL,
                  paid_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_quota (
                  user_id TEXT PRIMARY KEY,
                  remain_count INTEGER NOT NULL DEFAULT 0,
                  free_date TEXT NOT NULL DEFAULT '',
                  free_used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
        """将订单置为 PAID；已 PAID 时返回 False（幂等）。"""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,),
            ).fetchone()
            if row is None or str(row["status"]) == "PAID":
                return False
            conn.execute(
                """
                UPDATE payment_orders
                SET status = 'PAID', paid_at = ?
                WHERE out_trade_no = ?
                """,
                (paid_at or _utc_now_iso(), out_trade_no),
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
