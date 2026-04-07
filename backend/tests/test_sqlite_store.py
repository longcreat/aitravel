from __future__ import annotations

from pathlib import Path

from app.memory.sqlite_store import ChatSQLiteStore


def test_sqlite_store_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    store = ChatSQLiteStore(db_path)

    thread_id = "thread-a"
    store.append_user_message(thread_id, "这是一个非常长的第一句话用于测试标题规则")
    store.append_assistant_message(
        thread_id,
        "好的，这里是你的建议。",
        debug={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
    )

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].title == "这是一个非常长的第一..."

    detail = store.get_session_detail(thread_id)
    assert detail is not None
    assert len(detail.messages) == 2
    assert detail.messages[0].role == "user"
    assert detail.messages[1].text == "好的，这里是你的建议。"

    renamed = store.rename_session(thread_id, "杭州周末行")
    assert renamed is not None
    assert renamed.title == "杭州周末行"

    deleted = store.delete_session(thread_id)
    assert deleted is True
    assert store.get_session_detail(thread_id) is None
