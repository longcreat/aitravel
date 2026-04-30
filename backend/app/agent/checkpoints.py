"""Agent checkpoint 稳定点管理。"""

from __future__ import annotations

from app.agent.runtime import AgentRuntimeService
from app.memory.sqlite_store import ChatSQLiteStore


class AgentCheckpointService:
    """负责稳定 checkpoint 的定位、缓存和回滚。"""

    def __init__(self, chat_store: ChatSQLiteStore, runtime_service: AgentRuntimeService) -> None:
        self._chat_store = chat_store
        self._runtime_service = runtime_service

    async def delete_thread(self, thread_id: str) -> None:
        """删除线程对应的 LangGraph checkpoint 数据。"""
        runtime = self._runtime_service.runtime
        if runtime is None:
            return
        await runtime.checkpointer.adelete_thread(thread_id)

    async def rollback_thread(self, user_id: str, thread_id: str) -> None:
        """将线程回滚到最近一个合法 checkpoint。"""
        if self._runtime_service.runtime is None:
            return

        stable_checkpoint_id = self._resolve_persisted_checkpoint_id(user_id, thread_id)
        self._chat_store.set_stable_checkpoint_id(user_id, thread_id, stable_checkpoint_id)
        await self.prune_after(thread_id, stable_checkpoint_id)

    async def get_effective_checkpoint_id(self, user_id: str, thread_id: str) -> str | None:
        """读取线程当前应该作为下一轮起点的稳定 checkpoint。"""
        stable_checkpoint_id = self._chat_store.get_stable_checkpoint_id(user_id, thread_id)
        if stable_checkpoint_id:
            return stable_checkpoint_id

        stable_checkpoint_id = self._resolve_persisted_checkpoint_id(user_id, thread_id)
        if stable_checkpoint_id:
            self._chat_store.set_stable_checkpoint_id(user_id, thread_id, stable_checkpoint_id)
            return stable_checkpoint_id

        return self._chat_store.get_thread_root_checkpoint_id(thread_id)

    def _resolve_persisted_checkpoint_id(self, user_id: str, thread_id: str) -> str | None:
        """解析最近一个业务上已完成并可恢复的 checkpoint。"""
        return self._chat_store.get_latest_persisted_result_checkpoint_id(user_id, thread_id)

    async def get_latest_checkpoint_id(self, thread_id: str) -> str | None:
        """返回线程当前最新的 LangGraph checkpoint id。"""
        runtime = self._runtime_service.runtime
        if runtime is None:
            return None

        async for item in runtime.checkpointer.alist(
            {"configurable": {"thread_id": thread_id}},
            limit=1,
        ):
            return str(item.config["configurable"]["checkpoint_id"])
        return None

    async def prune_after(self, thread_id: str, checkpoint_id: str | None) -> None:
        """删除稳定点之后的半成品 checkpoint/writes。"""
        runtime = self._runtime_service.runtime
        if runtime is None:
            return

        checkpointer = runtime.checkpointer
        await checkpointer.setup()

        if checkpoint_id is None:
            await checkpointer.adelete_thread(thread_id)
            return

        async with checkpointer.lock, checkpointer.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT checkpoint_id
                FROM checkpoints
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id > ?
                ORDER BY checkpoint_id ASC
                """,
                (thread_id, checkpoint_id),
            )
            rows = await cur.fetchall()
            ids_to_delete = [str(row[0]) for row in rows]
            if not ids_to_delete:
                return

            placeholders = ",".join("?" for _ in ids_to_delete)
            await cur.execute(
                f"""
                DELETE FROM writes
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id IN ({placeholders})
                """,
                (thread_id, *ids_to_delete),
            )
            await cur.execute(
                f"""
                DELETE FROM checkpoints
                WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id IN ({placeholders})
                """,
                (thread_id, *ids_to_delete),
            )
            await checkpointer.conn.commit()
