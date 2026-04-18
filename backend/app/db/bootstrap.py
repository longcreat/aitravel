"""SQLite bootstrap 与 migration runner。"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}
_RESET_APPLIED: set[str] = set()


@dataclass(frozen=True)
class MigrationFile:
    """单个 SQL migration 文件。"""

    version: int
    name: str
    path: Path


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _migrations_dir() -> Path:
    return _backend_root() / "migrations"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_chat_sqlite_path() -> Path:
    """解析聊天数据库路径。"""
    return Path(os.getenv("CHAT_SQLITE_PATH", str(_backend_root() / "data" / "chat.db")))


def _should_reset_chat_db() -> bool:
    value = os.getenv("DEV_RESET_CHAT_DB", "").strip().lower()
    return value in _TRUTHY


def _discover_migrations() -> list[MigrationFile]:
    migrations: list[MigrationFile] = []
    for path in sorted(_migrations_dir().glob("*.sql")):
        prefix, _, suffix = path.stem.partition("_")
        if not prefix.isdigit() or not suffix:
            raise RuntimeError(f"非法 migration 文件名：{path.name}")
        migrations.append(MigrationFile(version=int(prefix), name=suffix, path=path))
    if not migrations:
        raise RuntimeError("未找到任何 migration SQL 文件")
    return migrations


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _connection(db_path: Path):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """
    )


def _guard_unversioned_app_database(conn: sqlite3.Connection) -> None:
    """拒绝继续运行未版本化的历史业务数据库。"""
    existing = _existing_tables(conn)
    if "schema_migrations" in existing:
        return

    app_tables = {
        "users",
        "email_login_codes",
        "chat_sessions",
        "chat_messages",
        "assistant_message_versions",
    }
    if existing & app_tables:
        raise RuntimeError(
            "检测到未版本化的历史 chat.db。请先设置 DEV_RESET_CHAT_DB=true 重建数据库，"
            "或手动删除旧数据库后重新启动。"
        )


def reset_sqlite_database(db_path: Path) -> None:
    """删除 SQLite 主文件及其 WAL/SHM 文件。"""
    for candidate in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm"), db_path):
        if candidate.exists():
            for _ in range(5):
                try:
                    candidate.unlink()
                    break
                except PermissionError:
                    time.sleep(0.05)
            else:
                candidate.unlink()


def run_sqlite_migrations(db_path: Path, *, target_version: int | None = None) -> list[int]:
    """按顺序执行未应用的 SQL migrations。"""
    migrations = _discover_migrations()
    if target_version is not None:
        migrations = [migration for migration in migrations if migration.version <= target_version]

    applied_versions: list[int] = []
    with _connection(db_path) as conn:
        _guard_unversioned_app_database(conn)
        _ensure_schema_migrations_table(conn)
        existing_versions = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC").fetchall()
        }

        for migration in migrations:
            if migration.version in existing_versions:
                continue
            script = migration.path.read_text(encoding="utf-8")
            conn.executescript(script)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.name, _utc_now_iso()),
            )
            applied_versions.append(migration.version)
    return applied_versions


def bootstrap_sqlite_database(db_path: Path | None = None, *, reset: bool | None = None) -> Path:
    """根据环境变量和显式参数完成 SQLite bootstrap。"""
    target = db_path or resolve_chat_sqlite_path()
    resolved_key = str(target.resolve())

    should_reset = _should_reset_chat_db() if reset is None else reset
    should_apply_reset = reset is True or (should_reset and resolved_key not in _RESET_APPLIED)
    if should_apply_reset:
        reset_sqlite_database(target)
        _RESET_APPLIED.add(resolved_key)

    run_sqlite_migrations(target)
    return target
