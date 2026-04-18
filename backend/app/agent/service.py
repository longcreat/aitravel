"""旅行 Agent 服务层门面。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.checkpoints import AgentCheckpointService
from app.agent.context import AgentRequestContext
from app.agent.presentation import build_final_response
from app.agent.runtime import AgentRuntimeService
from app.agent.streaming import AgentStreamService, StreamRunState
from app.llm.provider import (
    coerce_llm_profile_key,
    get_default_llm_profile_key,
    list_llm_profiles,
    resolve_llm_profile_key,
)
from app.memory.sqlite_store import ChatSQLiteStore
from app.observability.langsmith import langsmith_trace_context
from app.schemas.chat import (
    ChatInvokeRequest,
    ChatModelProfile,
    PersistedChatMessage,
    SessionDetail,
    SessionModelProfileState,
    SessionSummary,
)


class TravelAgentService:
    """旅行 Agent 业务门面。"""

    def __init__(self, mcp_config_path: Path, sqlite_db_path: Path) -> None:
        self._chat_store = ChatSQLiteStore(sqlite_db_path)
        self._runtime_service = AgentRuntimeService(mcp_config_path=mcp_config_path, sqlite_db_path=sqlite_db_path)
        self._checkpoint_service = AgentCheckpointService(
            chat_store=self._chat_store,
            runtime_service=self._runtime_service,
        )
        self._stream_service = AgentStreamService(runtime_service=self._runtime_service)

    async def startup(self) -> None:
        """初始化 Agent 运行时。"""
        await self._runtime_service.startup()

    async def shutdown(self) -> None:
        """关闭运行时关联的资源。"""
        await self._runtime_service.shutdown()

    def runtime_snapshot(self) -> dict[str, Any]:
        """返回当前运行时状态快照。"""
        return self._runtime_service.snapshot()

    def list_sessions(self, user_id: str) -> list[SessionSummary]:
        """返回会话摘要列表。"""
        return self._chat_store.list_sessions(user_id)

    def get_session_detail(self, user_id: str, thread_id: str) -> SessionDetail | None:
        """返回会话详情。"""
        detail = self._chat_store.get_session_detail(user_id, thread_id)
        if detail is None:
            return None
        detail.model_profile_key = coerce_llm_profile_key(detail.model_profile_key)
        return detail

    def list_model_profiles(self) -> list[ChatModelProfile]:
        """返回前端可见的模型档位列表。"""
        default_profile_key = get_default_llm_profile_key()
        return [
            ChatModelProfile(
                key=profile.key,
                label=profile.label,
                kind=profile.kind,  # type: ignore[arg-type]
                is_default=profile.key == default_profile_key,
            )
            for profile in list_llm_profiles()
        ]

    def update_session_model_profile(
        self, user_id: str, thread_id: str, model_profile_key: str
    ) -> SessionModelProfileState | None:
        """更新线程当前模型档位。"""
        resolved_profile_key = resolve_llm_profile_key(model_profile_key)
        updated = self._chat_store.set_session_model_profile_key(user_id, thread_id, resolved_profile_key)
        if not updated:
            return None
        return SessionModelProfileState(thread_id=thread_id, model_profile_key=resolved_profile_key)

    def rename_session(self, user_id: str, thread_id: str, title: str) -> SessionSummary | None:
        """重命名会话。"""
        return self._chat_store.rename_session(user_id, thread_id, title)

    async def delete_session(self, user_id: str, thread_id: str) -> bool:
        """删除会话及其 checkpoint。"""
        deleted = self._chat_store.delete_session(user_id, thread_id)
        if deleted:
            await self._checkpoint_service.delete_thread(thread_id)
        return deleted

    def switch_assistant_version(
        self, user_id: str, thread_id: str, assistant_message_id: int, version_id: int
    ) -> PersistedChatMessage | None:
        """切换 assistant 当前展示版本。"""
        return self._chat_store.switch_assistant_version(user_id, thread_id, assistant_message_id, version_id)

    def update_assistant_feedback(
        self, user_id: str, thread_id: str, assistant_message_id: int, version_id: int, feedback: str | None
    ) -> PersistedChatMessage | None:
        """更新 assistant version 点赞/点踩状态。"""
        return self._chat_store.update_assistant_feedback(user_id, thread_id, assistant_message_id, version_id, feedback)

    def _resolve_thread_model_profile_key(
        self, user_id: str, thread_id: str, requested_profile_key: str | None = None
    ) -> str:
        """解析当前线程本轮应使用的模型档位。"""
        stored_profile_key = self._chat_store.get_session_model_profile_key(user_id, thread_id)
        if stored_profile_key is not None:
            return coerce_llm_profile_key(stored_profile_key)
        return resolve_llm_profile_key(requested_profile_key)

    async def stream_regenerate(self, user_id: str, thread_id: str, assistant_message_id: int):
        """重新生成最新一条 assistant 回复。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        target = self._chat_store.get_regeneration_target(user_id, thread_id, assistant_message_id)
        if target is None:
            raise ValueError("Only the latest assistant message can be regenerated")
        model_profile_key = self._resolve_thread_model_profile_key(user_id, thread_id)

        state = StreamRunState()
        deferred_values_event: tuple[str, dict[str, Any]] | None = None

        with langsmith_trace_context(
            "chat.regenerate",
            user_id=user_id,
            thread_id=thread_id,
            model_profile_key=model_profile_key,
            extra_metadata={"assistant_message_id": assistant_message_id},
        ):
            try:
                async for event_name, event_payload in self._stream_service.stream_agent_run(
                    thread_id=thread_id,
                    user_message=target.user_message_text,
                    checkpoint_id=target.original_parent_checkpoint_id,
                    model_profile_key=model_profile_key,
                    state=state,
                    agent_context=AgentRequestContext(
                        user_id=user_id,
                        thread_id=thread_id,
                        model_profile_key=model_profile_key,
                    ),
                ):
                    if event_name == "values":
                        deferred_values_event = (event_name, event_payload)
                        continue
                    yield event_name, event_payload
            except BaseException:
                await self.rollback_thread(user_id, thread_id)
                raise

        final_response = build_final_response(
            latest_values=state.latest_values,
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.find_latest_valid_checkpoint_id(thread_id)
        self._chat_store.upsert_regenerated_version(
            user_id,
            thread_id,
            assistant_message_id,
            text=final_response.assistant_message,
            meta=final_response.meta.model_dump(),
            parent_checkpoint_id=target.original_parent_checkpoint_id,
            result_checkpoint_id=result_checkpoint_id,
        )
        self._chat_store.set_stable_checkpoint_id(user_id, thread_id, result_checkpoint_id)
        if deferred_values_event is not None:
            yield deferred_values_event

    async def stream_invoke(self, user_id: str, request: ChatInvokeRequest):
        """执行流式聊天并产出 LangGraph 原生流事件。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        model_profile_key = self._resolve_thread_model_profile_key(
            user_id, request.thread_id, request.model_profile_key
        )
        user_message_id = self._chat_store.append_user_message(
            user_id,
            request.thread_id,
            request.user_message,
            model_profile_key=model_profile_key,
        )
        checkpoint_id = await self._checkpoint_service.get_effective_checkpoint_id(user_id, request.thread_id)
        state = StreamRunState()

        with langsmith_trace_context(
            "chat.stream",
            user_id=user_id,
            thread_id=request.thread_id,
            locale=request.locale,
            model_profile_key=model_profile_key,
            extra_metadata={"session_meta_keys": sorted(request.session_meta.keys())},
        ):
            try:
                async for event_name, event_payload in self._stream_service.stream_agent_run(
                    thread_id=request.thread_id,
                    user_message=request.user_message,
                    checkpoint_id=checkpoint_id,
                    model_profile_key=model_profile_key,
                    state=state,
                    agent_context=AgentRequestContext(
                        user_id=user_id,
                        thread_id=request.thread_id,
                        locale=request.locale,
                        model_profile_key=model_profile_key,
                        session_meta=request.session_meta,
                    ),
                ):
                    yield event_name, event_payload
            except BaseException:
                await self.rollback_thread(user_id, request.thread_id)
                raise

        final_response = build_final_response(
            latest_values=state.latest_values,
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.find_latest_valid_checkpoint_id(request.thread_id)
        stored_parent_checkpoint_id = checkpoint_id or self._chat_store.get_thread_root_checkpoint_id(request.thread_id)

        self._chat_store.append_assistant_message(
            user_id,
            request.thread_id,
            final_response.assistant_message,
            meta=final_response.meta.model_dump(),
            reply_to_message_id=user_message_id,
            parent_checkpoint_id=stored_parent_checkpoint_id,
            result_checkpoint_id=result_checkpoint_id,
        )
        self._chat_store.set_stable_checkpoint_id(user_id, request.thread_id, result_checkpoint_id)

    async def rollback_thread(self, user_id: str, thread_id: str) -> None:
        """将线程回滚到最近一个合法的 checkpoint。"""
        await self._checkpoint_service.rollback_thread(user_id, thread_id)
