"""旅行 Agent 服务层门面。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent.checkpoints import AgentCheckpointService
from app.agent.context import AgentRequestContext
from app.agent.presentation import build_final_response, extract_latest_human_message_text
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
    ChatResumeRequest,
    PersistedChatMessage,
    SessionDetail,
    SessionModelProfileState,
    SessionSummary,
)
from app.speech.service import SpeechPlaybackTarget, SpeechService


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
        self._speech_service = SpeechService(chat_store=self._chat_store, sqlite_db_path=sqlite_db_path)

    async def startup(self) -> None:
        """初始化 Agent 运行时。"""
        await self._runtime_service.startup()

    async def shutdown(self) -> None:
        """关闭运行时关联的资源。"""
        await self._speech_service.shutdown()
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
        """删除会话及其 checkpoint，并联级删除对象存储中的语音文件。"""
        # 必须在删除 DB 记录之前收集 object_keys，否则 CASCADE 会先删除 speech_assets 行，导致查询返回空列表
        speech_object_keys = self._chat_store.get_thread_speech_object_keys(thread_id)
        deleted = self._chat_store.delete_session(user_id, thread_id)
        if deleted:
            await self._checkpoint_service.delete_thread(thread_id)
            await self._speech_service.delete_assets_by_keys(speech_object_keys)
        return deleted

    def switch_assistant_version(
        self, user_id: str, thread_id: str, assistant_message_id: str, version_id: str
    ) -> PersistedChatMessage | None:
        """切换 assistant 当前展示版本。"""
        return self._chat_store.switch_assistant_version(user_id, thread_id, assistant_message_id, version_id)

    def update_assistant_feedback(
        self, user_id: str, thread_id: str, assistant_message_id: str, version_id: str, feedback: str | None
    ) -> PersistedChatMessage | None:
        """更新 assistant version 点赞/点踩状态。"""
        return self._chat_store.update_assistant_feedback(user_id, thread_id, assistant_message_id, version_id, feedback)

    def get_speech_playback_url(
        self,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        version_id: str,
        *,
        base_url: str,
    ) -> tuple[str, str]:
        """返回 assistant version 的语音播放地址。"""
        return self._speech_service.build_playback_url(
            user_id=user_id,
            thread_id=thread_id,
            assistant_message_id=assistant_message_id,
            version_id=version_id,
            base_url=base_url,
        )

    def get_speech_playback_target(self, token: str) -> SpeechPlaybackTarget:
        """解析播放 token 并返回对应音频流。"""
        return self._speech_service.get_playback_target(token)

    def _resolve_thread_model_profile_key(
        self, user_id: str, thread_id: str, requested_profile_key: str | None = None
    ) -> str:
        """解析当前线程本轮应使用的模型档位。"""
        stored_profile_key = self._chat_store.get_session_model_profile_key(user_id, thread_id)
        if stored_profile_key is not None:
            return coerce_llm_profile_key(stored_profile_key)
        return resolve_llm_profile_key(requested_profile_key)

    def _persist_completed_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        user_message_text: str,
        model_profile_key: str,
        final_response,
        result_checkpoint_id: str | None,
        stored_parent_checkpoint_id: str | None,
        speech_job_id: str,
    ) -> None:
        """在一次完整对话结束后持久化用户消息与助手回复。"""
        user_message_id = self._chat_store.append_user_message(
            user_id,
            thread_id,
            user_message_text,
            model_profile_key=model_profile_key,
        )
        assistant_message_id, version_id = self._chat_store.append_assistant_message(
            user_id,
            thread_id,
            final_response.assistant_message,
            meta=final_response.meta.model_dump(),
            reply_to_message_id=user_message_id,
            parent_checkpoint_id=stored_parent_checkpoint_id,
            result_checkpoint_id=result_checkpoint_id,
        )
        self._speech_service.bind_generation(
            speech_job_id,
            user_id=user_id,
            thread_id=thread_id,
            assistant_message_id=assistant_message_id,
            version_id=version_id,
        )
        self._speech_service.finish_generation(speech_job_id, final_response.assistant_message)

    async def stream_regenerate(self, user_id: str, thread_id: str, assistant_message_id: str):
        """重新生成最新一条 assistant 回复。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        target = self._chat_store.get_regeneration_target(user_id, thread_id, assistant_message_id)
        if target is None:
            raise ValueError("Only the latest assistant message can be regenerated")
        model_profile_key = self._resolve_thread_model_profile_key(user_id, thread_id)

        state = StreamRunState()
        deferred_values_event: tuple[str, dict[str, Any]] | None = None
        speech_job_id = self._speech_service.start_generation(user_id, thread_id)

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
                    agent_input={"messages": [HumanMessage(content=target.user_message_text)]},
                    checkpoint_id=target.original_parent_checkpoint_id,
                    model_profile_key=model_profile_key,
                    state=state,
                    agent_context=AgentRequestContext(
                        user_id=user_id,
                        thread_id=thread_id,
                        model_profile_key=model_profile_key,
                    ),
                    on_assistant_text_chunk=lambda chunk: self._speech_service.append_text(speech_job_id, chunk),
                ):
                    if event_name == "interrupt":
                        raise ValueError("当前回复重新生成需要补充信息，请改为发送新消息")
                    if event_name == "values":
                        deferred_values_event = (event_name, event_payload)
                        continue
                    yield event_name, event_payload
            except BaseException:
                self._speech_service.cancel_generation(speech_job_id)
                await self.rollback_thread(user_id, thread_id)
                raise

        final_response = build_final_response(
            latest_values=state.latest_values,
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.find_latest_valid_checkpoint_id(thread_id)
        try:
            version_id = self._chat_store.upsert_regenerated_version(
                user_id,
                thread_id,
                assistant_message_id,
                text=final_response.assistant_message,
                meta=final_response.meta.model_dump(),
                parent_checkpoint_id=target.original_parent_checkpoint_id,
                result_checkpoint_id=result_checkpoint_id,
            )
            if version_id is not None:
                self._speech_service.bind_generation(
                    speech_job_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                )
                self._speech_service.finish_generation(speech_job_id, final_response.assistant_message)
            else:
                self._speech_service.cancel_generation(speech_job_id)
        except Exception:
            self._speech_service.cancel_generation(speech_job_id)
            raise
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
        checkpoint_id = await self._checkpoint_service.get_effective_checkpoint_id(user_id, request.thread_id)
        state = StreamRunState()
        speech_job_id = self._speech_service.start_generation(user_id, request.thread_id)

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
                    agent_input={"messages": [HumanMessage(content=request.user_message)]},
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
                    on_assistant_text_chunk=lambda chunk: self._speech_service.append_text(speech_job_id, chunk),
                ):
                    yield event_name, event_payload
            except BaseException:
                self._speech_service.cancel_generation(speech_job_id)
                await self.rollback_thread(user_id, request.thread_id)
                raise

        if state.interrupt is not None:
            self._speech_service.cancel_generation(speech_job_id)
            return

        final_response = build_final_response(
            latest_values=state.latest_values,
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.find_latest_valid_checkpoint_id(request.thread_id)
        stored_parent_checkpoint_id = checkpoint_id or self._chat_store.get_thread_root_checkpoint_id(request.thread_id)
        resolved_user_message_text = (
            extract_latest_human_message_text(state.latest_values.get("messages") if state.latest_values else None)
            or request.user_message
        )

        try:
            self._persist_completed_turn(
                user_id=user_id,
                thread_id=request.thread_id,
                user_message_text=resolved_user_message_text,
                model_profile_key=model_profile_key,
                final_response=final_response,
                result_checkpoint_id=result_checkpoint_id,
                stored_parent_checkpoint_id=stored_parent_checkpoint_id,
                speech_job_id=speech_job_id,
            )
        except Exception:
            self._speech_service.cancel_generation(speech_job_id)
            raise
        self._chat_store.set_stable_checkpoint_id(user_id, request.thread_id, result_checkpoint_id)

    async def stream_resume(self, user_id: str, request: ChatResumeRequest):
        """恢复一条被 interrupt 暂停的聊天。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        model_profile_key = self._resolve_thread_model_profile_key(
            user_id, request.thread_id, request.model_profile_key
        )
        state = StreamRunState()
        speech_job_id = self._speech_service.start_generation(user_id, request.thread_id)

        with langsmith_trace_context(
            "chat.resume",
            user_id=user_id,
            thread_id=request.thread_id,
            locale=request.locale,
            model_profile_key=model_profile_key,
            extra_metadata={"interrupt_id": request.interrupt_id},
        ):
            try:
                async for event_name, event_payload in self._stream_service.stream_agent_run(
                    thread_id=request.thread_id,
                    agent_input=Command(resume={request.interrupt_id: request.answer}),
                    checkpoint_id=None,
                    model_profile_key=model_profile_key,
                    state=state,
                    agent_context=AgentRequestContext(
                        user_id=user_id,
                        thread_id=request.thread_id,
                        locale=request.locale,
                        model_profile_key=model_profile_key,
                        session_meta=request.session_meta,
                    ),
                    on_assistant_text_chunk=lambda chunk: self._speech_service.append_text(speech_job_id, chunk),
                ):
                    yield event_name, event_payload
            except BaseException:
                self._speech_service.cancel_generation(speech_job_id)
                await self.rollback_thread(user_id, request.thread_id)
                raise

        if state.interrupt is not None:
            self._speech_service.cancel_generation(speech_job_id)
            return

        final_response = build_final_response(
            latest_values=state.latest_values,
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.find_latest_valid_checkpoint_id(request.thread_id)
        root_checkpoint_id = self._chat_store.get_thread_root_checkpoint_id(request.thread_id)
        stored_parent_checkpoint_id = self._chat_store.get_stable_checkpoint_id(user_id, request.thread_id) or root_checkpoint_id
        resolved_user_message_text = extract_latest_human_message_text(
            state.latest_values.get("messages") if state.latest_values else None
        )

        try:
            self._persist_completed_turn(
                user_id=user_id,
                thread_id=request.thread_id,
                user_message_text=resolved_user_message_text,
                model_profile_key=model_profile_key,
                final_response=final_response,
                result_checkpoint_id=result_checkpoint_id,
                stored_parent_checkpoint_id=stored_parent_checkpoint_id,
                speech_job_id=speech_job_id,
            )
        except Exception:
            self._speech_service.cancel_generation(speech_job_id)
            raise
        self._chat_store.set_stable_checkpoint_id(user_id, request.thread_id, result_checkpoint_id)

    async def rollback_thread(self, user_id: str, thread_id: str) -> None:
        """将线程回滚到最近一个合法的 checkpoint。"""
        await self._checkpoint_service.rollback_thread(user_id, thread_id)
