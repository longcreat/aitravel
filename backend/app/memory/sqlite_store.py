"""SQLite 聊天会话存储。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.schemas.chat import AssistantVersion, ChatMetaInfo, PersistedChatMessage, SessionDetail, SessionSummary


@dataclass
class AssistantMessageRegenerationTarget:
    """重新生成 assistant 回复所需的最小上下文。"""

    message_id: str
    reply_to_message_id: str
    user_message_text: str
    original_version_id: str
    original_parent_checkpoint_id: str | None
    current_version_id: str | None


@dataclass
class StoredAssistantMessageVersion:
    """内部使用的 assistant version 结构。"""

    id: str
    assistant_message_id: str
    version_index: int
    kind: str
    text: str
    meta: ChatMetaInfo | None
    feedback: str | None
    parent_checkpoint_id: str | None
    result_checkpoint_id: str | None
    speech_status: str | None
    speech_mime_type: str | None
    created_at: str


@dataclass
class StoredAssistantSpeechAsset:
    """内部使用的 assistant 语音资产结构。"""

    assistant_message_version_id: str
    status: str
    mime_type: str | None
    object_key: str | None
    error_message: str | None
    created_at: str
    updated_at: str


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间戳字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _new_chat_entity_id() -> str:
    """生成聊天域 opaque ID。"""
    return str(uuid4())


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

    MAX_ASSISTANT_VERSIONS = 3

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

    def _get_thread_root_checkpoint_id(self, conn: sqlite3.Connection, thread_id: str) -> str | None:
        """返回线程根 checkpoint。"""
        table_exists = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'checkpoints'
            """
        ).fetchone()
        if table_exists is None:
            return None

        row = conn.execute(
            """
            SELECT checkpoint_id
            FROM checkpoints
            WHERE thread_id = ? AND checkpoint_ns = '' AND parent_checkpoint_id IS NULL
            ORDER BY checkpoint_id ASC
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        value = row["checkpoint_id"]
        return str(value) if value else None

    def get_thread_root_checkpoint_id(self, thread_id: str) -> str | None:
        """公开读取线程根 checkpoint。"""
        with self._connection() as conn:
            return self._get_thread_root_checkpoint_id(conn, thread_id)

    def append_user_message(
        self, user_id: str, thread_id: str, text: str, *, model_profile_key: str = "standard"
    ) -> str:
        """写入用户消息，并在必要时创建会话。"""
        now = _utc_now_iso()
        message_id = _new_chat_entity_id()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT thread_id FROM chat_sessions WHERE thread_id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()

            if existing is None:
                title = _default_title_from_text(text)
                conn.execute(
                    """
                    INSERT INTO chat_sessions (
                      thread_id, user_id, title, custom_title, created_at, updated_at, last_message_preview, model_profile_key
                    ) VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (thread_id, user_id, title, now, now, _preview(text), model_profile_key),
                )
            else:
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET updated_at = ?, last_message_preview = ?
                    WHERE thread_id = ? AND user_id = ?
                    """,
                    (now, _preview(text), thread_id, user_id),
                )

            conn.execute(
                """
                INSERT INTO chat_messages (
                  id, thread_id, role, text, meta_json, reply_to_message_id, current_version_id, created_at
                ) VALUES (?, ?, 'user', ?, NULL, NULL, NULL, ?)
                """,
                (message_id, thread_id, text, now),
            )
        return message_id

    def append_assistant_message(
        self,
        user_id: str,
        thread_id: str,
        text: str,
        *,
        meta: dict[str, object],
        reply_to_message_id: str,
        parent_checkpoint_id: str | None,
        result_checkpoint_id: str | None,
    ) -> tuple[str, str]:
        """写入助手消息并更新会话活跃时间。"""
        now = _utc_now_iso()
        assistant_message_id = _new_chat_entity_id()
        version_id = _new_chat_entity_id()
        meta_json = json.dumps(meta, ensure_ascii=False)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                  id, thread_id, role, text, meta_json, reply_to_message_id, current_version_id, created_at
                ) VALUES (?, ?, 'assistant', ?, ?, ?, NULL, ?)
                """,
                (assistant_message_id, thread_id, text, meta_json, reply_to_message_id, now),
            )
            conn.execute(
                """
                INSERT INTO assistant_message_versions (
                  id,
                  assistant_message_id,
                  version_index,
                  kind,
                  text,
                  meta_json,
                  feedback,
                  parent_checkpoint_id,
                  result_checkpoint_id,
                  created_at
                ) VALUES (?, ?, 1, 'original', ?, ?, NULL, ?, ?, ?)
                """,
                (
                    version_id,
                    assistant_message_id,
                    text,
                    meta_json,
                    parent_checkpoint_id,
                    result_checkpoint_id,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE chat_messages
                SET current_version_id = ?
                WHERE id = ? AND thread_id = ?
                """,
                (version_id, assistant_message_id, thread_id),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?, last_message_preview = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (now, _preview(text), thread_id, user_id),
            )
        return assistant_message_id, version_id

    def _parse_meta_payload(self, meta_payload: str | None) -> ChatMetaInfo | None:
        if not meta_payload:
            return None
        return ChatMetaInfo.model_validate(json.loads(meta_payload))

    def _load_speech_assets_by_version_id(
        self, conn: sqlite3.Connection, thread_id: str
    ) -> dict[str, StoredAssistantSpeechAsset]:
        rows = conn.execute(
            """
            SELECT
              a.assistant_message_version_id,
              a.status,
              a.mime_type,
              a.object_key,
              a.error_message,
              a.created_at,
              a.updated_at
            FROM assistant_version_speech_assets a
            INNER JOIN assistant_message_versions v ON v.id = a.assistant_message_version_id
            INNER JOIN chat_messages m ON m.id = v.assistant_message_id
            WHERE m.thread_id = ?
            """,
            (thread_id,),
        ).fetchall()

        return {
            str(row["assistant_message_version_id"]): StoredAssistantSpeechAsset(
                assistant_message_version_id=str(row["assistant_message_version_id"]),
                status=str(row["status"]),
                mime_type=str(row["mime_type"]) if row["mime_type"] else None,
                object_key=str(row["object_key"]) if row["object_key"] else None,
                error_message=str(row["error_message"]) if row["error_message"] else None,
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        }

    def _load_versions_by_message_id(
        self, conn: sqlite3.Connection, thread_id: str
    ) -> dict[str, list[StoredAssistantMessageVersion]]:
        speech_assets_by_version_id = self._load_speech_assets_by_version_id(conn, thread_id)
        rows = conn.execute(
            """
            SELECT
              v.id,
              v.assistant_message_id,
              v.version_index,
              v.kind,
              v.text,
              v.meta_json,
              v.feedback,
              v.parent_checkpoint_id,
              v.result_checkpoint_id,
              v.created_at
            FROM assistant_message_versions v
            INNER JOIN chat_messages m ON m.id = v.assistant_message_id
            WHERE m.thread_id = ?
            ORDER BY m.created_at ASC, m.rowid ASC, v.version_index ASC
            """,
            (thread_id,),
        ).fetchall()

        grouped: dict[str, list[StoredAssistantMessageVersion]] = {}
        for row in rows:
            version_id = str(row["id"])
            speech_asset = speech_assets_by_version_id.get(version_id)
            item = StoredAssistantMessageVersion(
                id=version_id,
                assistant_message_id=str(row["assistant_message_id"]),
                version_index=int(row["version_index"]),
                kind=str(row["kind"]),
                text=str(row["text"]),
                meta=self._parse_meta_payload(row["meta_json"]),
                feedback=str(row["feedback"]) if row["feedback"] else None,
                parent_checkpoint_id=str(row["parent_checkpoint_id"]) if row["parent_checkpoint_id"] else None,
                result_checkpoint_id=str(row["result_checkpoint_id"]) if row["result_checkpoint_id"] else None,
                speech_status=speech_asset.status if speech_asset else None,
                speech_mime_type=speech_asset.mime_type if speech_asset else None,
                created_at=str(row["created_at"]),
            )
            grouped.setdefault(item.assistant_message_id, []).append(item)
        return grouped

    def list_sessions(self, user_id: str) -> list[SessionSummary]:
        """按最近活跃时间倒序返回当前用户会话摘要。"""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT thread_id, title, created_at, updated_at, last_message_preview
                FROM chat_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
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

    def get_session_detail(self, user_id: str, thread_id: str) -> SessionDetail | None:
        """获取指定用户会话详情。"""
        with self._connection() as conn:
            session_row = conn.execute(
                """
                SELECT thread_id, title, created_at, updated_at, model_profile_key
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()
            if session_row is None:
                return None

            message_rows = conn.execute(
                """
                SELECT id, role, text, meta_json, reply_to_message_id, current_version_id, created_at
                FROM chat_messages
                WHERE thread_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (thread_id,),
            ).fetchall()
            versions_by_message_id = self._load_versions_by_message_id(conn, thread_id)

        messages: list[PersistedChatMessage] = []
        latest_assistant_id = next(
            (str(row["id"]) for row in reversed(message_rows) if str(row["role"]) == "assistant"),
            None,
        )
        for row in message_rows:
            message_id = str(row["id"])
            role = str(row["role"])
            version_models = [
                AssistantVersion(
                    id=version.id,
                    version_index=version.version_index,  # type: ignore[arg-type]
                    kind=version.kind,  # type: ignore[arg-type]
                    text=version.text,
                    meta=version.meta,
                    feedback=version.feedback,  # type: ignore[arg-type]
                    speech_status=version.speech_status,  # type: ignore[arg-type]
                    speech_mime_type=version.speech_mime_type,
                    created_at=version.created_at,
                )
                for version in versions_by_message_id.get(message_id, [])
            ]
            has_regenerable_original_version = any(
                version.version_index == 1 and bool(version.parent_checkpoint_id)
                for version in versions_by_message_id.get(message_id, [])
            )
            messages.append(
                PersistedChatMessage(
                    id=message_id,
                    role=role,  # type: ignore[arg-type]
                    text=str(row["text"]),
                    meta=self._parse_meta_payload(row["meta_json"]),
                    reply_to_message_id=str(row["reply_to_message_id"]) if row["reply_to_message_id"] else None,
                    current_version_id=str(row["current_version_id"]) if row["current_version_id"] else None,
                    versions=version_models,
                    can_regenerate=role == "assistant"
                    and message_id == latest_assistant_id
                    and has_regenerable_original_version,
                    created_at=str(row["created_at"]),
                )
            )

        return SessionDetail(
            thread_id=str(session_row["thread_id"]),
            title=str(session_row["title"]),
            created_at=str(session_row["created_at"]),
            updated_at=str(session_row["updated_at"]),
            model_profile_key=str(session_row["model_profile_key"] or "standard"),
            messages=messages,
        )

    def get_session_model_profile_key(self, user_id: str, thread_id: str) -> str | None:
        """读取当前用户会话绑定的模型档位。"""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT model_profile_key
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        value = row["model_profile_key"]
        return str(value) if value else None

    def set_session_model_profile_key(self, user_id: str, thread_id: str, model_profile_key: str) -> bool:
        """更新当前用户会话绑定的模型档位。"""
        with self._connection() as conn:
            result = conn.execute(
                """
                UPDATE chat_sessions
                SET model_profile_key = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (model_profile_key, thread_id, user_id),
            )
        return result.rowcount > 0

    def rename_session(self, user_id: str, thread_id: str, title: str) -> SessionSummary | None:
        """重命名当前用户会话。"""
        normalized = title.strip()
        if not normalized:
            return None

        now = _utc_now_iso()
        with self._connection() as conn:
            result = conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, custom_title = 1, updated_at = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (normalized, now, thread_id, user_id),
            )
            if result.rowcount == 0:
                return None

            row = conn.execute(
                """
                SELECT thread_id, title, created_at, updated_at, last_message_preview
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()

        if row is None:
            return None
        return SessionSummary(
            thread_id=str(row["thread_id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_message_preview=str(row["last_message_preview"]),
        )

    def delete_session(self, user_id: str, thread_id: str) -> bool:
        """删除当前用户会话。"""
        with self._connection() as conn:
            result = conn.execute(
                "DELETE FROM chat_sessions WHERE thread_id = ? AND user_id = ?",
                (thread_id, user_id),
            )
            deleted = result.rowcount > 0
        return deleted

    def get_regeneration_target(
        self, user_id: str, thread_id: str, assistant_message_id: str
    ) -> AssistantMessageRegenerationTarget | None:
        """返回重新生成 assistant 回复所需上下文。"""
        with self._connection() as conn:
            latest_assistant_row = conn.execute(
                """
                SELECT id
                FROM chat_messages
                WHERE thread_id = ? AND role = 'assistant'
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
            if latest_assistant_row is None or str(latest_assistant_row["id"]) != assistant_message_id:
                return None

            row = conn.execute(
                """
                SELECT
                  m.id,
                  m.reply_to_message_id,
                  m.current_version_id,
                  reply.text AS user_message_text,
                  original.id AS original_version_id,
                  original.parent_checkpoint_id AS original_parent_checkpoint_id
                FROM chat_messages m
                INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                INNER JOIN chat_messages reply ON reply.id = m.reply_to_message_id
                INNER JOIN assistant_message_versions original
                  ON original.assistant_message_id = m.id AND original.version_index = 1
                WHERE
                  m.thread_id = ?
                  AND m.id = ?
                  AND m.role = 'assistant'
                  AND s.user_id = ?
                """,
                (thread_id, assistant_message_id, user_id),
            ).fetchone()

        if row is None:
            return None
        original_parent_checkpoint_id = (
            str(row["original_parent_checkpoint_id"])
            if row["original_parent_checkpoint_id"]
            else None
        )
        if original_parent_checkpoint_id is None:
            return None

        return AssistantMessageRegenerationTarget(
            message_id=str(row["id"]),
            reply_to_message_id=str(row["reply_to_message_id"]),
            user_message_text=str(row["user_message_text"]),
            original_version_id=str(row["original_version_id"]),
            original_parent_checkpoint_id=original_parent_checkpoint_id,
            current_version_id=str(row["current_version_id"]) if row["current_version_id"] else None,
        )

    def upsert_regenerated_version(
        self,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        *,
        text: str,
        meta: dict[str, object],
        parent_checkpoint_id: str | None,
        result_checkpoint_id: str | None,
    ) -> str | None:
        """写入新的重生版本并切到该版本。最多保留 3 个版本（原始版 + 2 次重生）。"""
        now = _utc_now_iso()
        version_id = _new_chat_entity_id()
        meta_json = json.dumps(meta, ensure_ascii=False)
        with self._connection() as conn:
            owner = conn.execute(
                """
                SELECT 1
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()
            if owner is None:
                return None

            max_row = conn.execute(
                """
                SELECT MAX(version_index) AS max_idx
                FROM assistant_message_versions
                WHERE assistant_message_id = ?
                """,
                (assistant_message_id,),
            ).fetchone()
            next_version_index = (max_row["max_idx"] or 1) + 1
            if next_version_index > self.MAX_ASSISTANT_VERSIONS:
                raise ValueError("最多生成三次无法重新生成")

            conn.execute(
                """
                INSERT INTO assistant_message_versions (
                  id,
                  assistant_message_id,
                  version_index,
                  kind,
                  text,
                  meta_json,
                  feedback,
                  parent_checkpoint_id,
                  result_checkpoint_id,
                  created_at
                ) VALUES (?, ?, ?, 'regenerated', ?, ?, NULL, ?, ?, ?)
                """,
                (
                    version_id,
                    assistant_message_id,
                    next_version_index,
                    text,
                    meta_json,
                    parent_checkpoint_id,
                    result_checkpoint_id,
                    now,
                ),
            )

            conn.execute(
                """
                UPDATE chat_messages
                SET text = ?, meta_json = ?, current_version_id = ?
                WHERE id = ? AND thread_id = ?
                """,
                (text, meta_json, version_id, assistant_message_id, thread_id),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?, last_message_preview = ?, stable_checkpoint_id = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (now, _preview(text), result_checkpoint_id, thread_id, user_id),
            )
        return version_id

    def switch_assistant_version(
        self, user_id: str, thread_id: str, assistant_message_id: str, version_id: str
    ) -> PersistedChatMessage | None:
        """切换 assistant 当前展示版本。"""
        with self._connection() as conn:
            latest_assistant_row = conn.execute(
                """
                SELECT id
                FROM chat_messages
                WHERE thread_id = ? AND role = 'assistant'
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
            if latest_assistant_row is None or str(latest_assistant_row["id"]) != assistant_message_id:
                return None

            version_row = conn.execute(
                """
                SELECT
                  v.id,
                  v.text,
                  v.meta_json,
                  v.result_checkpoint_id
                FROM assistant_message_versions v
                INNER JOIN chat_messages m ON m.id = v.assistant_message_id
                INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                WHERE
                  m.thread_id = ?
                  AND m.id = ?
                  AND v.id = ?
                  AND s.user_id = ?
                """,
                (thread_id, assistant_message_id, version_id, user_id),
            ).fetchone()
            if version_row is None:
                return None

            meta_json = str(version_row["meta_json"]) if version_row["meta_json"] else None
            conn.execute(
                """
                UPDATE chat_messages
                SET text = ?, meta_json = ?, current_version_id = ?
                WHERE id = ? AND thread_id = ?
                """,
                (str(version_row["text"]), meta_json, version_id, assistant_message_id, thread_id),
            )
            conn.execute(
                """
                UPDATE chat_sessions
                SET stable_checkpoint_id = ?, last_message_preview = ?, updated_at = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (
                    str(version_row["result_checkpoint_id"]) if version_row["result_checkpoint_id"] else None,
                    _preview(str(version_row["text"])),
                    _utc_now_iso(),
                    thread_id,
                    user_id,
                ),
            )

        detail = self.get_session_detail(user_id, thread_id)
        if detail is None:
            return None
        return next((message for message in detail.messages if message.id == assistant_message_id), None)

    def update_assistant_feedback(
        self, user_id: str, thread_id: str, assistant_message_id: str, version_id: str, feedback: str | None
    ) -> PersistedChatMessage | None:
        """更新 assistant version 点赞/点踩状态。"""
        with self._connection() as conn:
            result = conn.execute(
                """
                UPDATE assistant_message_versions
                SET feedback = ?
                WHERE id = ?
                  AND assistant_message_id = ?
                  AND assistant_message_id IN (
                    SELECT m.id
                    FROM chat_messages m
                    INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                    WHERE m.thread_id = ? AND s.user_id = ?
                  )
                """,
                (feedback, version_id, assistant_message_id, thread_id, user_id),
            )
            if result.rowcount == 0:
                return None

        detail = self.get_session_detail(user_id, thread_id)
        if detail is None:
            return None
        return next((message for message in detail.messages if message.id == assistant_message_id), None)

    def upsert_speech_asset(
        self,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        version_id: str,
        *,
        status: str,
        mime_type: str | None,
        object_key: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """创建或更新 assistant version 语音资产。"""
        now = _utc_now_iso()
        speech_asset_id = _new_chat_entity_id()
        with self._connection() as conn:
            owner = conn.execute(
                """
                SELECT 1
                FROM assistant_message_versions v
                INNER JOIN chat_messages m ON m.id = v.assistant_message_id
                INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                WHERE v.id = ? AND m.id = ? AND m.thread_id = ? AND s.user_id = ?
                """,
                (version_id, assistant_message_id, thread_id, user_id),
            ).fetchone()
            if owner is None:
                return False

            conn.execute(
                """
                INSERT INTO assistant_version_speech_assets (
                  id,
                  assistant_message_version_id,
                  status,
                  mime_type,
                  object_key,
                  error_message,
                  created_at,
                  updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assistant_message_version_id) DO UPDATE SET
                  status = excluded.status,
                  mime_type = excluded.mime_type,
                  object_key = excluded.object_key,
                  error_message = excluded.error_message,
                  updated_at = excluded.updated_at
                """,
                (speech_asset_id, version_id, status, mime_type, object_key, error_message, now, now),
            )
        return True

    def get_speech_asset(
        self, user_id: str, thread_id: str, assistant_message_id: str, version_id: str
    ) -> StoredAssistantSpeechAsset | None:
        """读取 assistant version 语音资产。"""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                  a.assistant_message_version_id,
                  a.status,
                  a.mime_type,
                  a.object_key,
                  a.error_message,
                  a.created_at,
                  a.updated_at
                FROM assistant_version_speech_assets a
                INNER JOIN assistant_message_versions v ON v.id = a.assistant_message_version_id
                INNER JOIN chat_messages m ON m.id = v.assistant_message_id
                INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                WHERE v.id = ? AND m.id = ? AND m.thread_id = ? AND s.user_id = ?
                """,
                (version_id, assistant_message_id, thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return StoredAssistantSpeechAsset(
            assistant_message_version_id=str(row["assistant_message_version_id"]),
            status=str(row["status"]),
            mime_type=str(row["mime_type"]) if row["mime_type"] else None,
            object_key=str(row["object_key"]) if row["object_key"] else None,
            error_message=str(row["error_message"]) if row["error_message"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_thread_speech_object_keys(self, thread_id: str) -> list[str]:
        """返回会话下所有已上传语音文件的 object key 列表。"""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a.object_key
                FROM assistant_version_speech_assets a
                INNER JOIN assistant_message_versions v ON v.id = a.assistant_message_version_id
                INNER JOIN chat_messages m ON m.id = v.assistant_message_id
                WHERE m.thread_id = ? AND a.object_key IS NOT NULL
                """,
                (thread_id,),
            ).fetchall()
        return [str(row["object_key"]) for row in rows]

    def get_stable_checkpoint_id(self, user_id: str, thread_id: str) -> str | None:
        """读取当前用户会话记录的稳定 checkpoint。"""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT stable_checkpoint_id
                FROM chat_sessions
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        value = row["stable_checkpoint_id"]
        return str(value) if value else None

    def get_latest_persisted_result_checkpoint_id(self, user_id: str, thread_id: str) -> str | None:
        """读取最近一条已持久化 assistant 当前版本对应的结果 checkpoint。"""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT v.result_checkpoint_id
                FROM chat_messages m
                INNER JOIN chat_sessions s ON s.thread_id = m.thread_id
                INNER JOIN assistant_message_versions v ON v.id = m.current_version_id
                WHERE
                  m.thread_id = ?
                  AND s.user_id = ?
                  AND m.role = 'assistant'
                  AND m.current_version_id IS NOT NULL
                ORDER BY m.created_at DESC, m.rowid DESC
                LIMIT 1
                """,
                (thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        value = row["result_checkpoint_id"]
        return str(value) if value else None

    def set_stable_checkpoint_id(self, user_id: str, thread_id: str, checkpoint_id: str | None) -> None:
        """更新当前用户会话的稳定 checkpoint。"""
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET stable_checkpoint_id = ?
                WHERE thread_id = ? AND user_id = ?
                """,
                (checkpoint_id, thread_id, user_id),
            )
