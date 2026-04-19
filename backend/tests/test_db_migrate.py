from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from app.db.bootstrap import bootstrap_sqlite_database, run_sqlite_migrations


def test_bootstrap_sqlite_database_creates_full_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"

    bootstrap_sqlite_database(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "schema_migrations",
        "users",
        "email_login_codes",
        "chat_sessions",
        "chat_messages",
        "assistant_message_versions",
        "assistant_version_speech_assets",
    } <= tables


def test_run_sqlite_migrations_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"

    first = run_sqlite_migrations(db_path)
    second = run_sqlite_migrations(db_path)

    assert first == [1, 2, 3, 4]
    assert second == []


def test_bootstrap_sqlite_database_reset_recreates_database(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    bootstrap_sqlite_database(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (999, 'fake', '2026-04-08T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    time.sleep(0.1)
    bootstrap_sqlite_database(db_path, reset=True)

    conn = sqlite3.connect(db_path)
    try:
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC").fetchall()]
    finally:
        conn.close()

    assert versions == [1, 2, 3, 4]


def test_run_sqlite_migrations_rejects_unversioned_legacy_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE chat_sessions (
              thread_id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="未版本化"):
        run_sqlite_migrations(db_path)


def test_run_sqlite_migrations_rejects_versioned_legacy_integer_chat_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-versioned.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TEXT NOT NULL
            );

            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (1, 'auth_tables', '2026-04-19T00:00:00Z');

            CREATE TABLE chat_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              thread_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              reply_to_message_id INTEGER,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="整数型聊天 schema"):
        run_sqlite_migrations(db_path)
