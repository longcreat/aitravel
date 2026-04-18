"""命令行 migration 入口。"""

from __future__ import annotations

import argparse

from app.db.bootstrap import bootstrap_sqlite_database, resolve_chat_sqlite_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQLite migrations for the chat database.")
    parser.add_argument("--reset", action="store_true", help="Delete the database file before running migrations.")
    args = parser.parse_args()

    db_path = resolve_chat_sqlite_path()
    bootstrap_sqlite_database(db_path, reset=args.reset)
    print(f"SQLite 数据库已就绪：{db_path}")


if __name__ == "__main__":
    main()
