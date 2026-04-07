"""SQLite 聊天会话存储。

该模块负责会话与消息的本地持久化，支持：
- 会话列表查询
- 会话详情查询
- 会话重命名
- 会话删除（级联删除消息）
- 聊天消息写入（用户/助手）
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.schemas.chat import (
    ChatDebugInfo,
    PersistedChatMessage,
    SessionDetail,
    SessionSummary,
)


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间戳字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _default_title_from_text(text: str) -> str:
    """按规则生成默认会话标题。"""
    normalized = text.strip()
    if not normalized:
        return "新会话"
    if len(normalized) <= 10:
        return normalized
    return f"{normalized[:10]}..."


def _preview(text: str, max_len: int = 80) -> str:
    """生成会话预览文本。"""
    normalized = text.strip()
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len]}..."


class ChatSQLiteStore:
    """聊天 SQLite 存储实现。"""

    def __init__(self, db_path: Path) -> None:
        """初始化存储并自动建表。

        Args:
            db_path: SQLite 文件路径。
        """
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接并启用外键约束。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        """初始化数据库表结构与索引。"""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                  thread_id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  custom_title INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  last_message_preview TEXT NOT NULL DEFAULT '',
                  stable_checkpoint_id TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                  text TEXT NOT NULL,
                  debug_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (thread_id) REFERENCES chat_sessions(thread_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                  ON chat_sessions(updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_messages_thread_id_id
                  ON chat_messages(thread_id, id);
                """
            )
            conn.commit()

    def append_user_message(self, thread_id: str, text: str) -> None:
        """写入用户消息，并在必要时创建会话。"""
        now = _utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT thread_id FROM chat_sessions WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()

            if existing is None:
                title = _default_title_from_text(text)
                conn.execute(
                    """
                    INSERT INTO chat_sessions (
                      thread_id, title, custom_title, created_at, updated_at, last_message_preview
                    ) VALUES (?, ?, 0, ?, ?, ?)
                    """,
                    (thread_id, title, now, now, _preview(text)),
                )
            else:
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = ?, last_message_preview = ?
                    WHERE thread_id = ?
                    """,
                    (now, _preview(text), thread_id),
                )

            conn.execute(
                """
                INSERT INTO chat_messages (
                  thread_id, role, text, debug_json, created_at
                ) VALUES (?, 'user', ?, NULL, ?)
                """,
                (thread_id, text, now),
            )
            conn.commit()

    def append_assistant_message(
        self,
        thread_id: str,
        text: str,
        *,
        debug: dict[str, object],
    ) -> None:
        """写入助手消息并更新会话更新时间。"""
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                  thread_id, role, text, debug_json, created_at
                ) VALUES (?, 'assistant', ?, ?, ?)
                """,
                (
                    thread_id,
                    text,
                    json.dumps(debug, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?, last_message_preview = ?
                WHERE thread_id = ?
                """,
                (now, _preview(text), thread_id),
            )
            conn.commit()

    def list_sessions(self) -> list[SessionSummary]:
        """按 `updated_at` 倒序返回会话摘要。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT thread_id, title, created_at, updated_at, last_message_preview
                FROM chat_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return [
            SessionSummary(
                thread_id=str(row["thread_id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                last_message_preview=str(row["last_message_preview"]),
            )
            for row in rows
        ]

    def get_session_detail(self, thread_id: str) -> SessionDetail | None:
        """获取会话详情（含消息列表）。"""
        with self._connect() as conn:
            session_row = conn.execute(
                """
                SELECT thread_id, title, created_at, updated_at
                FROM chat_sessions
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            if session_row is None:
                return None

            message_rows = conn.execute(
                """
                SELECT id, role, text, debug_json, created_at
                FROM chat_messages
                WHERE thread_id = ?
                ORDER BY id ASC
                """,
                (thread_id,),
            ).fetchall()

        messages: list[PersistedChatMessage] = []
        for row in message_rows:
            debug_payload = row["debug_json"]
            debug_data = json.loads(debug_payload) if debug_payload else None

            messages.append(
                PersistedChatMessage(
                    id=int(row["id"]),
                    role=str(row["role"]),  # type: ignore[arg-type]
                    text=str(row["text"]),
                    debug=ChatDebugInfo.model_validate(debug_data) if debug_data else None,
                    created_at=str(row["created_at"]),
                )
            )

        return SessionDetail(
            thread_id=str(session_row["thread_id"]),
            title=str(session_row["title"]),
            created_at=str(session_row["created_at"]),
            updated_at=str(session_row["updated_at"]),
            messages=messages,
        )

    def rename_session(self, thread_id: str, title: str) -> SessionSummary | None:
        """重命名会话并返回更新后的摘要。"""
        normalized = title.strip()
        if not normalized:
            return None

        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, custom_title = 1, updated_at = ?
                WHERE thread_id = ?
                """,
                (normalized, _utc_now_iso(), thread_id),
            )
            conn.commit()
            if result.rowcount == 0:
                return None

        # 返回更新后的摘要，复用查询逻辑确保结构统一。
        summary = next((item for item in self.list_sessions() if item.thread_id == thread_id), None)
        return summary

    def delete_session(self, thread_id: str) -> bool:
        """删除会话及其消息。"""
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM chat_sessions WHERE thread_id = ?",
                (thread_id,),
            )
            conn.commit()
            return result.rowcount > 0

    def get_stable_checkpoint_id(self, thread_id: str) -> str | None:
        """读取会话当前记录的稳定 checkpoint id。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stable_checkpoint_id FROM chat_sessions WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        value = row["stable_checkpoint_id"]
        return str(value) if value else None

    def set_stable_checkpoint_id(self, thread_id: str, checkpoint_id: str | None) -> None:
        """更新会话当前可安全恢复的稳定 checkpoint id。"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET stable_checkpoint_id = ?
                WHERE thread_id = ?
                """,
                (checkpoint_id, thread_id),
            )
            conn.commit()
