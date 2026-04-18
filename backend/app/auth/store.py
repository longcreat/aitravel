"""认证 SQLite 存储。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.auth import AuthPurpose, AuthUser


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


class AuthSQLiteStore:
    """认证相关 SQLite 存储实现。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  email TEXT NOT NULL UNIQUE,
                  nickname TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_login_codes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL,
                  purpose TEXT NOT NULL CHECK(purpose IN ('login', 'register')),
                  code_hash TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  consumed_at TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_email
                  ON users(email);

                CREATE INDEX IF NOT EXISTS idx_email_login_codes_lookup
                  ON email_login_codes(email, purpose, created_at DESC);
                """
            )
            conn.commit()

    def get_user_by_email(self, email: str) -> AuthUser | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, nickname, created_at, updated_at
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()
        if row is None:
            return None
        return AuthUser(
            id=str(row["id"]),
            email=str(row["email"]),
            nickname=str(row["nickname"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, nickname, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return AuthUser(
            id=str(row["id"]),
            email=str(row["email"]),
            nickname=str(row["nickname"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def create_user(self, email: str) -> AuthUser:
        now = _utc_now_iso()
        nickname = email.split("@", 1)[0].strip() or "旅行用户"
        user_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, nickname, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, nickname, now, now),
            )
            conn.commit()
        return AuthUser(id=user_id, email=email, nickname=nickname, created_at=now, updated_at=now)

    def save_email_code(self, *, email: str, purpose: AuthPurpose, code_hash: str, expires_at: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE email_login_codes
                SET consumed_at = ?
                WHERE email = ? AND purpose = ? AND consumed_at IS NULL
                """,
                (now, email, purpose),
            )
            conn.execute(
                """
                INSERT INTO email_login_codes (email, purpose, code_hash, expires_at, consumed_at, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (email, purpose, code_hash, expires_at, now),
            )
            conn.commit()

    def get_latest_email_code(self, *, email: str, purpose: AuthPurpose) -> dict[str, str | int | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, purpose, code_hash, expires_at, consumed_at, created_at
                FROM email_login_codes
                WHERE email = ? AND purpose = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "email": str(row["email"]),
            "purpose": str(row["purpose"]),
            "code_hash": str(row["code_hash"]),
            "expires_at": str(row["expires_at"]),
            "consumed_at": str(row["consumed_at"]) if row["consumed_at"] else None,
            "created_at": str(row["created_at"]),
        }

    def consume_email_code(self, code_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE email_login_codes
                SET consumed_at = ?
                WHERE id = ?
                """,
                (_utc_now_iso(), code_id),
            )
            conn.commit()
