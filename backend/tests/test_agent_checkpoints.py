from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.checkpoints import AgentCheckpointService


class _FakeChatStore:
    def __init__(
        self,
        *,
        stable_checkpoint_id: str | None = None,
        persisted_checkpoint_id: str | None = None,
        root_checkpoint_id: str | None = None,
    ) -> None:
        self._stable_checkpoint_id = stable_checkpoint_id
        self._persisted_checkpoint_id = persisted_checkpoint_id
        self._root_checkpoint_id = root_checkpoint_id
        self.set_calls: list[tuple[str, str, str | None]] = []

    def get_stable_checkpoint_id(self, _user_id: str, _thread_id: str) -> str | None:
        return self._stable_checkpoint_id

    def get_latest_persisted_result_checkpoint_id(self, _user_id: str, _thread_id: str) -> str | None:
        return self._persisted_checkpoint_id

    def get_thread_root_checkpoint_id(self, _thread_id: str) -> str | None:
        return self._root_checkpoint_id

    def set_stable_checkpoint_id(self, user_id: str, thread_id: str, checkpoint_id: str | None) -> None:
        self.set_calls.append((user_id, thread_id, checkpoint_id))


class _FakeCursor:
    def __init__(self, ids_to_delete: list[str]) -> None:
        self._ids_to_delete = ids_to_delete
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def execute(self, sql: str, params: tuple[object, ...]) -> _FakeCursor:
        self.executed.append((" ".join(sql.split()), params))
        return self

    async def fetchall(self) -> list[tuple[str]]:
        return [(checkpoint_id,) for checkpoint_id in self._ids_to_delete]


class _FakeConnection:
    def __init__(self, ids_to_delete: list[str]) -> None:
        self._ids_to_delete = ids_to_delete
        self.cursors: list[_FakeCursor] = []
        self.committed = False

    def cursor(self) -> _FakeCursor:
        cursor = _FakeCursor(self._ids_to_delete)
        self.cursors.append(cursor)
        return cursor

    async def commit(self) -> None:
        self.committed = True


class _FakeCheckpointer:
    def __init__(self, ids_to_delete: list[str]) -> None:
        self.lock = asyncio.Lock()
        self.conn = _FakeConnection(ids_to_delete)
        self.setup_called = False
        self.deleted_threads: list[str] = []

    async def setup(self) -> None:
        self.setup_called = True

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)


@pytest.mark.asyncio
async def test_get_effective_checkpoint_id_prefers_session_stable_checkpoint() -> None:
    service = AgentCheckpointService(
        chat_store=_FakeChatStore(
            stable_checkpoint_id="cp-stable",
            persisted_checkpoint_id="cp-persisted",
            root_checkpoint_id="cp-root",
        ),
        runtime_service=SimpleNamespace(runtime=None),
    )

    checkpoint_id = await service.get_effective_checkpoint_id("user-1", "thread-1")

    assert checkpoint_id == "cp-stable"


@pytest.mark.asyncio
async def test_get_effective_checkpoint_id_falls_back_to_persisted_checkpoint_then_root() -> None:
    store = _FakeChatStore(
        stable_checkpoint_id=None,
        persisted_checkpoint_id="cp-persisted",
        root_checkpoint_id="cp-root",
    )
    service = AgentCheckpointService(chat_store=store, runtime_service=SimpleNamespace(runtime=None))

    checkpoint_id = await service.get_effective_checkpoint_id("user-1", "thread-1")

    assert checkpoint_id == "cp-persisted"
    assert store.set_calls == [("user-1", "thread-1", "cp-persisted")]

    root_only_store = _FakeChatStore(
        stable_checkpoint_id=None,
        persisted_checkpoint_id=None,
        root_checkpoint_id="cp-root",
    )
    root_only_service = AgentCheckpointService(chat_store=root_only_store, runtime_service=SimpleNamespace(runtime=None))

    root_checkpoint_id = await root_only_service.get_effective_checkpoint_id("user-1", "thread-2")

    assert root_checkpoint_id == "cp-root"
    assert root_only_store.set_calls == []


@pytest.mark.asyncio
async def test_rollback_thread_prunes_after_latest_persisted_checkpoint() -> None:
    chat_store = _FakeChatStore(
        stable_checkpoint_id=None,
        persisted_checkpoint_id="cp-persisted",
        root_checkpoint_id="cp-root",
    )
    checkpointer = _FakeCheckpointer(ids_to_delete=["cp-after-1", "cp-after-2"])
    runtime_service = SimpleNamespace(runtime=SimpleNamespace(checkpointer=checkpointer))
    service = AgentCheckpointService(chat_store=chat_store, runtime_service=runtime_service)

    await service.rollback_thread("user-1", "thread-1")

    assert chat_store.set_calls == [("user-1", "thread-1", "cp-persisted")]
    assert checkpointer.setup_called is True
    assert checkpointer.conn.committed is True
    cursor = checkpointer.conn.cursors[0]
    assert cursor.executed[0][1] == ("thread-1", "cp-persisted")
    assert cursor.executed[1][1] == ("thread-1", "cp-after-1", "cp-after-2")
    assert cursor.executed[2][1] == ("thread-1", "cp-after-1", "cp-after-2")
