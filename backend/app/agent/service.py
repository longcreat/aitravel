"""旅行 Agent 服务层门面。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.checkpoints import AgentCheckpointService
from app.agent.context import AgentRequestContext
from app.agent.presentation import _content_to_text, build_final_response
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
    ChatMessagePart,
    ChatReasoningPart,
    ChatTextPart,
    ChatInvokeRequest,
    ChatModelProfile,
    MessageCompletedPayload,
    PersistedChatMessage,
    SessionDetail,
    SessionModelProfileState,
    SessionSummary,
    TurnDonePayload,
    TurnStartPayload,
)
from app.speech.service import SpeechPlaybackTarget, SpeechService

logger = logging.getLogger(__name__)


def _finalize_ui_parts(
    parts: list[ChatMessagePart],
    assistant_text: str,
    reasoning_text: str | None,
) -> list[ChatMessagePart]:
    """返回完成态 UI parts，必要时从最终文本补齐。"""
    if not parts:
        completed: list[ChatMessagePart] = []
        if reasoning_text:
            completed.append(ChatReasoningPart(id="reasoning-1", text=reasoning_text, status="completed"))
        if assistant_text:
            completed.append(ChatTextPart(id="text-1", text=assistant_text, status="completed"))
        return completed

    finalized: list[ChatMessagePart] = []
    for part in parts:
        if part.type in {"text", "reasoning"}:
            part.status = "completed"  # type: ignore[attr-defined]
        finalized.append(part)

    has_text = any(part.type == "text" and getattr(part, "text", "") for part in finalized)
    if assistant_text and not has_text:
        finalized.append(ChatTextPart(id="text-1", text=assistant_text, status="completed"))
    return finalized


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

    def _complete_assistant_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        version_id: str,
        final_response,
        parts: list[ChatMessagePart],
        result_checkpoint_id: str | None,
        speech_job_id: str,
    ) -> PersistedChatMessage:
        """完成一次流式 assistant 回复并返回稳定展示态。"""
        message = self._chat_store.complete_assistant_message(
            user_id,
            thread_id,
            assistant_message_id,
            version_id,
            text=final_response.assistant_message,
            parts=_finalize_ui_parts(parts, final_response.assistant_message, final_response.meta.reasoning_text),
            meta=final_response.meta.model_dump(),
            result_checkpoint_id=result_checkpoint_id,
        )
        if message is None:
            raise RuntimeError("Failed to complete assistant message")
        self._speech_service.finish_generation(speech_job_id, final_response.assistant_message)
        return message

    def _log_pipeline_failure(
        self,
        action: str,
        *,
        user_id: str,
        thread_id: str,
        model_profile_key: str,
        checkpoint_id: str | None,
    ) -> None:
        """记录聊天主链路异常，便于后端排查。"""
        logger.exception(
            "%s failed user_id=%s thread_id=%s model_profile_key=%s checkpoint_id=%s",
            action,
            user_id,
            thread_id,
            model_profile_key,
            checkpoint_id,
        )

    async def stream_regenerate(self, user_id: str, thread_id: str, assistant_message_id: str):
        """重新生成最新一条 assistant 回复。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        target = self._chat_store.get_regeneration_target(user_id, thread_id, assistant_message_id)
        if target is None:
            raise ValueError("Only the latest assistant message can be regenerated")
        model_profile_key = self._resolve_thread_model_profile_key(user_id, thread_id)

        state = StreamRunState()
        version_id = self._chat_store.begin_regenerated_version(
            user_id,
            thread_id,
            assistant_message_id,
            parent_checkpoint_id=target.original_parent_checkpoint_id,
        )
        if version_id is None:
            raise ValueError("Assistant message or version not found")
        speech_job_id = self._speech_service.start_generation(user_id, thread_id)
        self._speech_service.bind_generation(
            speech_job_id,
            user_id=user_id,
            thread_id=thread_id,
            assistant_message_id=assistant_message_id,
            version_id=version_id,
        )
        assistant_placeholder = self._chat_store.get_message(user_id, thread_id, assistant_message_id)
        if assistant_placeholder is None:
            raise ValueError("Assistant message or version not found")
        yield "turn.start", TurnStartPayload(thread_id=thread_id, assistant_message=assistant_placeholder).model_dump()

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
                    assistant_message_id=assistant_message_id,
                    version_id=version_id,
                    on_assistant_text_chunk=lambda chunk: self._speech_service.append_text(speech_job_id, chunk),
                ):
                    yield event_name, event_payload
            except BaseException as exc:
                if not isinstance(exc, asyncio.CancelledError):
                    self._log_pipeline_failure(
                        "chat.regenerate",
                        user_id=user_id,
                        thread_id=thread_id,
                        model_profile_key=model_profile_key,
                        checkpoint_id=target.original_parent_checkpoint_id,
                    )
                self._speech_service.cancel_generation(speech_job_id)
                await self.rollback_thread(user_id, thread_id)
                self._chat_store.discard_assistant_version(
                    user_id,
                    thread_id,
                    assistant_message_id,
                    version_id,
                    target.current_version_id,
                )
                raise

        final_response = build_final_response(
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.get_latest_checkpoint_id(thread_id)
        try:
            completed_message = self._complete_assistant_turn(
                user_id=user_id,
                thread_id=thread_id,
                assistant_message_id=assistant_message_id,
                version_id=version_id,
                final_response=final_response,
                parts=state.ui_parts,
                result_checkpoint_id=result_checkpoint_id,
                speech_job_id=speech_job_id,
            )
        except Exception:
            self._speech_service.cancel_generation(speech_job_id)
            raise
        self._chat_store.set_stable_checkpoint_id(user_id, thread_id, result_checkpoint_id)
        yield "message.completed", MessageCompletedPayload(message=completed_message).model_dump()
        yield "turn.done", TurnDonePayload(thread_id=thread_id).model_dump()

    async def stream_invoke(self, user_id: str, request: ChatInvokeRequest):
        """执行流式聊天并产出 LangGraph 原生流事件。"""
        if self._runtime_service.runtime is None:
            await self.startup()

        model_profile_key = self._resolve_thread_model_profile_key(
            user_id, request.thread_id, request.model_profile_key
        )
        checkpoint_id = await self._checkpoint_service.get_effective_checkpoint_id(user_id, request.thread_id)
        state = StreamRunState()
        stored_parent_checkpoint_id = checkpoint_id or self._chat_store.get_thread_root_checkpoint_id(request.thread_id)
        user_message_id = self._chat_store.append_user_message(
            user_id,
            request.thread_id,
            request.user_message,
            model_profile_key=model_profile_key,
        )
        assistant_placeholder = self._chat_store.begin_assistant_message(
            user_id,
            request.thread_id,
            reply_to_message_id=user_message_id,
            parent_checkpoint_id=stored_parent_checkpoint_id,
        )
        version_id = assistant_placeholder.current_version_id
        if version_id is None:
            raise RuntimeError("Assistant version missing")
        speech_job_id = self._speech_service.start_generation(user_id, request.thread_id)
        self._speech_service.bind_generation(
            speech_job_id,
            user_id=user_id,
            thread_id=request.thread_id,
            assistant_message_id=assistant_placeholder.id,
            version_id=version_id,
        )
        user_message = self._chat_store.get_message(user_id, request.thread_id, user_message_id)
        yield "turn.start", TurnStartPayload(
            thread_id=request.thread_id,
            user_message=user_message,
            assistant_message=assistant_placeholder,
        ).model_dump()

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
                    assistant_message_id=assistant_placeholder.id,
                    version_id=version_id,
                    on_assistant_text_chunk=lambda chunk: self._speech_service.append_text(speech_job_id, chunk),
                ):
                    yield event_name, event_payload
            except BaseException as exc:
                is_cancelled = isinstance(exc, asyncio.CancelledError)
                if not is_cancelled:
                    self._log_pipeline_failure(
                        "chat.stream",
                        user_id=user_id,
                        thread_id=request.thread_id,
                        model_profile_key=model_profile_key,
                        checkpoint_id=checkpoint_id,
                    )
                self._speech_service.cancel_generation(speech_job_id)
                await self.rollback_thread(user_id, request.thread_id)
                stopped_status = "stopped" if is_cancelled else "failed"
                stopped_text = (
                    _content_to_text(state.accumulated_chunk.content).strip()
                    if state.accumulated_chunk else ""
                ) if is_cancelled else "当前请求失败，可能是网络或后端服务异常。"
                stopped_parts = (
                    _finalize_ui_parts(state.ui_parts, stopped_text, None)
                    if is_cancelled and state.ui_parts
                    else [ChatTextPart(id="text-1", text=stopped_text or "已停止生成。", status=stopped_status)]
                )
                for part in stopped_parts:
                    if hasattr(part, "status"):
                        part.status = stopped_status  # type: ignore[attr-defined]
                stopped_message = self._chat_store.complete_assistant_message(
                    user_id,
                    request.thread_id,
                    assistant_placeholder.id,
                    version_id,
                    text=stopped_text or ("已停止生成。" if is_cancelled else "当前请求失败，可能是网络或后端服务异常。"),
                    parts=stopped_parts,
                    meta={},
                    result_checkpoint_id=None,
                    status=stopped_status,
                )
                if stopped_message is not None:
                    yield "message.completed", MessageCompletedPayload(message=stopped_message).model_dump()
                raise

        final_response = build_final_response(
            accumulated_chunk=state.accumulated_chunk,
            streamed_tool_traces=state.streamed_tool_traces,
            runtime=self._runtime_service.require_runtime(),
        )
        result_checkpoint_id = await self._checkpoint_service.get_latest_checkpoint_id(request.thread_id)
        try:
            completed_message = self._complete_assistant_turn(
                user_id=user_id,
                thread_id=request.thread_id,
                assistant_message_id=assistant_placeholder.id,
                version_id=version_id,
                final_response=final_response,
                parts=state.ui_parts,
                result_checkpoint_id=result_checkpoint_id,
                speech_job_id=speech_job_id,
            )
        except Exception:
            self._speech_service.cancel_generation(speech_job_id)
            raise
        self._chat_store.set_stable_checkpoint_id(user_id, request.thread_id, result_checkpoint_id)
        yield "message.completed", MessageCompletedPayload(message=completed_message).model_dump()
        yield "turn.done", TurnDonePayload(thread_id=request.thread_id).model_dump()

    async def rollback_thread(self, user_id: str, thread_id: str) -> None:
        """将线程回滚到最近一个合法的 checkpoint。"""
        await self._checkpoint_service.rollback_thread(user_id, thread_id)
