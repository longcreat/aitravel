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

    assert {"schema_migrations", "users", "email_login_codes", "chat_sessions", "chat_messages", "assistant_message_versions"} <= tables


def test_run_sqlite_migrations_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"

    first = run_sqlite_migrations(db_path)
    second = run_sqlite_migrations(db_path)

    assert first == [1, 2, 3]
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

    assert versions == [1, 2, 3]


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
