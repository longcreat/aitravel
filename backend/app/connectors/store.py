"""Connector 授权与 OAuth state 的 SQLite 存储。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.connectors import ConnectorAuthStatus


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuthorizationRow:
    """`user_mcp_authorizations` 表的行模型。"""

    id: str
    user_id: str
    connector_id: str
    mcp_server_url: str
    authorization_server: str | None
    client_id: str | None
    client_secret_enc: str | None
    redirect_uri: str
    access_token_enc: str | None
    refresh_token_enc: str | None
    token_type: str
    scope: str | None
    expires_at: str | None
    status: ConnectorAuthStatus
    last_error: str | None
    created_at: str
    updated_at: str


@dataclass
class OAuthStateRow:
    """`connector_oauth_states` 表的行模型。"""

    state: str
    user_id: str
    connector_id: str
    authorization_id: str
    code_verifier: str
    redirect_after: str | None
    expires_at: str
    created_at: str


def _row_to_authorization(row: sqlite3.Row) -> AuthorizationRow:
    return AuthorizationRow(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        connector_id=str(row["connector_id"]),
        mcp_server_url=str(row["mcp_server_url"]),
        authorization_server=str(row["authorization_server"]) if row["authorization_server"] else None,
        client_id=str(row["client_id"]) if row["client_id"] else None,
        client_secret_enc=str(row["client_secret_enc"]) if row["client_secret_enc"] else None,
        redirect_uri=str(row["redirect_uri"]),
        access_token_enc=str(row["access_token_enc"]) if row["access_token_enc"] else None,
        refresh_token_enc=str(row["refresh_token_enc"]) if row["refresh_token_enc"] else None,
        token_type=str(row["token_type"] or "bearer"),
        scope=str(row["scope"]) if row["scope"] else None,
        expires_at=str(row["expires_at"]) if row["expires_at"] else None,
        status=str(row["status"]),  # type: ignore[arg-type]
        last_error=str(row["last_error"]) if row["last_error"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class ConnectorAuthStore:
    """`user_mcp_authorizations` + `connector_oauth_states` 的 SQLite 适配器。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

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

    # ---- authorizations ----

    def upsert_authorization_record(
        self,
        *,
        user_id: str,
        connector_id: str,
        mcp_server_url: str,
        redirect_uri: str,
    ) -> AuthorizationRow:
        """确保 (user_id, connector_id) 维度的授权记录存在，返回当前记录。

        如果上次已经成功授权，这次会保留现有 token 并仅刷新元数据。
        """
        now = _utc_now_iso()
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT * FROM user_mcp_authorizations
                WHERE user_id = ? AND connector_id = ?
                """,
                (user_id, connector_id),
            ).fetchone()

            if existing is None:
                authorization_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO user_mcp_authorizations (
                        id, user_id, connector_id, mcp_server_url, authorization_server,
                        client_id, client_secret_enc, redirect_uri,
                        access_token_enc, refresh_token_enc, token_type, scope, expires_at,
                        status, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, 'bearer', NULL, NULL, 'pending', NULL, ?, ?)
                    """,
                    (authorization_id, user_id, connector_id, mcp_server_url, redirect_uri, now, now),
                )
                row = conn.execute(
                    "SELECT * FROM user_mcp_authorizations WHERE id = ?",
                    (authorization_id,),
                ).fetchone()
            else:
                conn.execute(
                    """
                    UPDATE user_mcp_authorizations
                    SET mcp_server_url = ?, redirect_uri = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (mcp_server_url, redirect_uri, now, existing["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM user_mcp_authorizations WHERE id = ?",
                    (existing["id"],),
                ).fetchone()

        return _row_to_authorization(row)

    def update_client_credentials(
        self,
        authorization_id: str,
        *,
        authorization_server: str,
        client_id: str,
        client_secret_enc: str | None,
    ) -> None:
        """写入动态注册得到的 OAuth client 凭证。"""
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_mcp_authorizations
                SET authorization_server = ?, client_id = ?, client_secret_enc = ?, updated_at = ?
                WHERE id = ?
                """,
                (authorization_server, client_id, client_secret_enc, now, authorization_id),
            )

    def update_authorization_server(self, authorization_id: str, authorization_server: str) -> None:
        """记录 RFC 9728 发现得到的授权服务器地址。"""
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_mcp_authorizations
                SET authorization_server = ?, updated_at = ?
                WHERE id = ?
                """,
                (authorization_server, now, authorization_id),
            )

    def save_tokens(
        self,
        authorization_id: str,
        *,
        access_token_enc: str,
        refresh_token_enc: str | None,
        token_type: str,
        scope: str | None,
        expires_at: str | None,
    ) -> None:
        """写入访问令牌并把状态翻到 connected。"""
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_mcp_authorizations
                SET access_token_enc = ?,
                    refresh_token_enc = COALESCE(?, refresh_token_enc),
                    token_type = ?,
                    scope = ?,
                    expires_at = ?,
                    status = 'connected',
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (access_token_enc, refresh_token_enc, token_type, scope, expires_at, now, authorization_id),
            )

    def mark_failed(self, authorization_id: str, error: str) -> None:
        """记录授权失败信息（不删除记录，方便用户重试）。"""
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_mcp_authorizations
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error[:500], now, authorization_id),
            )

    def mark_revoked(self, authorization_id: str) -> None:
        """断开授权：清空 token 并将状态置为 revoked。"""
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE user_mcp_authorizations
                SET access_token_enc = NULL,
                    refresh_token_enc = NULL,
                    expires_at = NULL,
                    status = 'revoked',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, authorization_id),
            )

    def list_for_user(self, user_id: str) -> list[AuthorizationRow]:
        """返回该用户的全部授权记录。"""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_mcp_authorizations
                WHERE user_id = ?
                ORDER BY connector_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_authorization(row) for row in rows]

    def list_connected(self, user_id: str) -> list[AuthorizationRow]:
        """返回该用户当前已成功授权的记录。"""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_mcp_authorizations
                WHERE user_id = ? AND status = 'connected'
                ORDER BY connector_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_authorization(row) for row in rows]

    def get_for_user(self, user_id: str, connector_id: str) -> AuthorizationRow | None:
        """读取指定用户对指定 connector 的授权记录。"""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM user_mcp_authorizations
                WHERE user_id = ? AND connector_id = ?
                """,
                (user_id, connector_id),
            ).fetchone()
        return _row_to_authorization(row) if row else None

    def get_by_id(self, authorization_id: str) -> AuthorizationRow | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_mcp_authorizations WHERE id = ?",
                (authorization_id,),
            ).fetchone()
        return _row_to_authorization(row) if row else None

    # ---- oauth states ----

    def save_oauth_state(self, payload: OAuthStateRow) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO connector_oauth_states (
                    state, user_id, connector_id, authorization_id, code_verifier,
                    redirect_after, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.state,
                    payload.user_id,
                    payload.connector_id,
                    payload.authorization_id,
                    payload.code_verifier,
                    payload.redirect_after,
                    payload.expires_at,
                    payload.created_at,
                ),
            )

    def consume_oauth_state(self, state: str) -> OAuthStateRow | None:
        """取走（删除）一条 OAuth state，避免重放。"""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM connector_oauth_states WHERE state = ?",
                (state,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM connector_oauth_states WHERE state = ?", (state,))

        return OAuthStateRow(
            state=str(row["state"]),
            user_id=str(row["user_id"]),
            connector_id=str(row["connector_id"]),
            authorization_id=str(row["authorization_id"]),
            code_verifier=str(row["code_verifier"]),
            redirect_after=str(row["redirect_after"]) if row["redirect_after"] else None,
            expires_at=str(row["expires_at"]),
            created_at=str(row["created_at"]),
        )

    def purge_expired_states(self) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM connector_oauth_states WHERE expires_at < ?",
                (_utc_now_iso(),),
            )
