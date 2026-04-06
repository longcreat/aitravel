"""Agent 记忆运行时构建。"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


async def build_memory_runtime(db_path: Path) -> tuple[AsyncSqliteSaver, None]:
    """构建 Agent 运行时记忆组件。

    使用 LangGraph 官方 SQLite checkpointer 承担运行时会话记忆。
    当前 Agent 未使用 Shared Values，因此不额外注入 store。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(str(db_path))
    saver = AsyncSqliteSaver(connection)
    await saver.setup()
    return saver, None
