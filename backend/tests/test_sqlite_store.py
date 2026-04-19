from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.store import AuthSQLiteStore
from app.db.bootstrap import bootstrap_sqlite_database, run_sqlite_migrations
from app.memory.sqlite_store import ChatSQLiteStore


def test_sqlite_store_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    bootstrap_sqlite_database(db_path)
    auth_store = AuthSQLiteStore(db_path)
    store = ChatSQLiteStore(db_path)
    user = auth_store.create_user("demo@example.com")

    thread_id = "thread-a"
    user_message_id = store.append_user_message(user.id, thread_id, "这是一个非常长的第一句话用于测试标题规则")
    assert isinstance(user_message_id, str)
    assistant_message_id, original_version_id = store.append_assistant_message(
        user.id,
        thread_id,
        "好的，这里是你的建议。",
        meta={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
        reply_to_message_id=user_message_id,
        parent_checkpoint_id="cp-parent-1",
        result_checkpoint_id="cp-result-1",
    )
    assert isinstance(assistant_message_id, str)
    assert isinstance(original_version_id, str)

    sessions = store.list_sessions(user.id)
    assert len(sessions) == 1
    assert sessions[0].title == "这是一个非常长的第一..."

    detail = store.get_session_detail(user.id, thread_id)
    assert detail is not None
    assert detail.model_profile_key == "standard"
    assert len(detail.messages) == 2
    assert detail.messages[0].role == "user"
    assert detail.messages[1].text == "好的，这里是你的建议。"
    assert detail.messages[1].meta is not None
    assert detail.messages[1].meta.tool_traces == []
    assert detail.messages[1].reply_to_message_id == user_message_id
    assert detail.messages[1].current_version_id == original_version_id
    assert len(detail.messages[1].versions) == 1
    assert detail.messages[1].versions[0].kind == "original"
    assert detail.messages[1].can_regenerate is True
    assert store.get_latest_persisted_result_checkpoint_id(user.id, thread_id) == "cp-result-1"

    assert store.upsert_speech_asset(
        user.id,
        thread_id,
        assistant_message_id,
        original_version_id,
        status="generating",
        mime_type="audio/mpeg",
    ) is True
    speech_asset = store.get_speech_asset(user.id, thread_id, assistant_message_id, original_version_id)
    assert speech_asset is not None
    assert speech_asset.status == "generating"
    assert speech_asset.mime_type == "audio/mpeg"

    detail_with_speech = store.get_session_detail(user.id, thread_id)
    assert detail_with_speech is not None
    assert detail_with_speech.messages[1].versions[0].speech_status == "generating"
    assert detail_with_speech.messages[1].versions[0].speech_mime_type == "audio/mpeg"

    regeneration_target = store.get_regeneration_target(user.id, thread_id, assistant_message_id)
    assert regeneration_target is not None
    assert regeneration_target.user_message_text == "这是一个非常长的第一句话用于测试标题规则"
    assert regeneration_target.original_parent_checkpoint_id == "cp-parent-1"

    regenerated_version_id = store.upsert_regenerated_version(
        user.id,
        thread_id,
        assistant_message_id,
        text="这是重生成后的建议。",
        meta={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
        parent_checkpoint_id="cp-parent-1",
        result_checkpoint_id="cp-result-2",
    )
    assert regenerated_version_id is not None
    assert isinstance(regenerated_version_id, str)

    regenerated_version_id_2 = store.upsert_regenerated_version(
        user.id,
        thread_id,
        assistant_message_id,
        text="这是第二次重生成后的建议。",
        meta={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
        parent_checkpoint_id="cp-parent-1",
        result_checkpoint_id="cp-result-3",
    )
    assert regenerated_version_id_2 is not None
    assert isinstance(regenerated_version_id_2, str)
    assert store.get_latest_persisted_result_checkpoint_id(user.id, thread_id) == "cp-result-3"

    with pytest.raises(ValueError, match="最多生成三次无法重新生成"):
        store.upsert_regenerated_version(
            user.id,
            thread_id,
            assistant_message_id,
            text="这是第三次重生成后的建议。",
            meta={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
            parent_checkpoint_id="cp-parent-1",
            result_checkpoint_id="cp-result-4",
        )

    switched = store.switch_assistant_version(user.id, thread_id, assistant_message_id, regenerated_version_id_2)
    assert switched is not None
    assert switched.text == "这是第二次重生成后的建议。"
    assert switched.current_version_id == regenerated_version_id_2
    assert len(switched.versions) == 3
    assert store.get_latest_persisted_result_checkpoint_id(user.id, thread_id) == "cp-result-3"

    rated = store.update_assistant_feedback(user.id, thread_id, assistant_message_id, regenerated_version_id_2, "up")
    assert rated is not None
    assert rated.versions[2].feedback == "up"

    renamed = store.rename_session(user.id, thread_id, "杭州周末行")
    assert renamed is not None
    assert renamed.title == "杭州周末行"

    deleted = store.delete_session(user.id, thread_id)
    assert deleted is True
    assert store.get_session_detail(user.id, thread_id) is None


def test_sqlite_store_bootstraps_from_versioned_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "versioned-chat.db"

    applied_initial = run_sqlite_migrations(db_path, target_version=1)
    assert applied_initial == [1]

    applied_remaining = run_sqlite_migrations(db_path)
    assert applied_remaining == [2, 3, 4]

    store = ChatSQLiteStore(db_path)
    auth_store = AuthSQLiteStore(db_path)
    user = auth_store.create_user("demo@example.com")

    user_message_id = store.append_user_message(user.id, "thread-b", "帮我推荐两天行程")
    assistant_message_id, current_version_id = store.append_assistant_message(
        user.id,
        "thread-b",
        "这里是原始回复。",
        meta={"tool_traces": [], "mcp_connected_servers": [], "mcp_errors": []},
        reply_to_message_id=user_message_id,
        parent_checkpoint_id="cp-parent",
        result_checkpoint_id="cp-result",
    )

    detail = store.get_session_detail(user.id, "thread-b")
    assert detail is not None
    assert detail.model_profile_key == "standard"
    assert detail.messages[1].id == assistant_message_id
    assert detail.messages[1].current_version_id == current_version_id
    assert isinstance(current_version_id, str)


def test_sqlite_store_updates_session_model_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    bootstrap_sqlite_database(db_path)
    auth_store = AuthSQLiteStore(db_path)
    store = ChatSQLiteStore(db_path)
    user = auth_store.create_user("demo@example.com")

    store.append_user_message(user.id, "thread-c", "先聊一下", model_profile_key="thinking")

    assert store.get_session_model_profile_key(user.id, "thread-c") == "thinking"
    assert store.set_session_model_profile_key(user.id, "thread-c", "standard") is True
    assert store.get_session_model_profile_key(user.id, "thread-c") == "standard"
