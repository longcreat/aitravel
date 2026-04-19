"""语音播报服务。"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import jwt

from app.memory.sqlite_store import ChatSQLiteStore
from app.speech.object_store import SpeechObjectStore, build_speech_object_store

_DEFAULT_SPEECH_MIME_TYPE = "audio/mpeg"
_PLAYBACK_TOKEN_TTL_SECONDS = 60 * 10
_JOB_SENTINEL = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


@dataclass
class SpeechPlaybackTarget:
    media_type: str
    iterator: AsyncIterator[bytes]


@dataclass
class SpeechGenerationJob:
    """单条语音生成任务。"""

    id: str
    loop: asyncio.AbstractEventLoop
    user_id: str
    thread_id: str
    spool_path: Path
    mime_type: str = _DEFAULT_SPEECH_MIME_TYPE
    assistant_message_id: str | None = None
    version_id: str | None = None
    text_queue: queue.Queue[object] = field(default_factory=queue.Queue)
    update_event: asyncio.Event = field(default_factory=asyncio.Event)
    completed_event: asyncio.Event = field(default_factory=asyncio.Event)
    failed_event: asyncio.Event = field(default_factory=asyncio.Event)
    bytes_written: int = 0
    text_enqueued: bool = False
    text_completed: bool = False
    stream_completed: bool = False
    cancelled: bool = False
    finalize_started: bool = False
    cleanup_requested: bool = False
    cleanup_done: bool = False
    error_message: str | None = None
    object_key: str | None = None
    active_readers: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def notify_update(self) -> None:
        self.loop.call_soon_threadsafe(self.update_event.set)

    def mark_audio_chunk(self, data_size: int) -> None:
        with self.lock:
            self.bytes_written += data_size
        self.notify_update()

    def mark_stream_completed(self) -> None:
        with self.lock:
            self.stream_completed = True
        self.loop.call_soon_threadsafe(self.completed_event.set)
        self.notify_update()

    def mark_failed(self, error_message: str) -> None:
        with self.lock:
            self.error_message = error_message
        self.loop.call_soon_threadsafe(self.failed_event.set)
        self.loop.call_soon_threadsafe(self.completed_event.set)
        self.notify_update()


class SpeechService:
    """协调语音生成、持久化和播放。"""

    def __init__(self, chat_store: ChatSQLiteStore, sqlite_db_path: Path) -> None:
        self._chat_store = chat_store
        self._sqlite_db_path = sqlite_db_path
        self._data_root = sqlite_db_path.parent / "speech"
        self._spool_root = self._data_root / "spool"
        self._asset_root = self._data_root / "assets"
        self._spool_root.mkdir(parents=True, exist_ok=True)
        self._asset_root.mkdir(parents=True, exist_ok=True)
        self._object_store: SpeechObjectStore = build_speech_object_store(self._asset_root)
        self._jobs_by_id: dict[str, SpeechGenerationJob] = {}
        self._jobs_by_version_id: dict[str, SpeechGenerationJob] = {}
        self._jobs_lock = threading.Lock()
        self._jwt_secret = os.getenv("JWT_SECRET", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self._tts_api_key and self._jwt_secret)

    @property
    def _tts_api_key(self) -> str:
        return os.getenv("ALIYUN_TTS_API_KEY", "").strip()

    @property
    def _tts_ws_url(self) -> str:
        return os.getenv("ALIYUN_TTS_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference").strip()

    @property
    def _tts_model(self) -> str:
        return os.getenv("ALIYUN_TTS_MODEL", "cosyvoice-v3-flash").strip() or "cosyvoice-v3-flash"

    @property
    def _tts_voice(self) -> str:
        return os.getenv("ALIYUN_TTS_VOICE", "longanyang").strip() or "longanyang"

    async def shutdown(self) -> None:
        """停止当前进程内所有语音任务。"""
        with self._jobs_lock:
            jobs = list(self._jobs_by_id.values())
        for job in jobs:
            self.cancel_generation(job.id)

    def start_generation(self, user_id: str, thread_id: str) -> str | None:
        """启动流式语音生成任务。"""
        if not self.enabled:
            return None

        loop = asyncio.get_running_loop()
        job_id = str(uuid4())
        job = SpeechGenerationJob(
            id=job_id,
            loop=loop,
            user_id=user_id,
            thread_id=thread_id,
            spool_path=self._spool_root / f"{job_id}.mp3",
        )
        with self._jobs_lock:
            self._jobs_by_id[job_id] = job

        worker = threading.Thread(target=self._run_generation_worker, args=(job,), daemon=True)
        worker.start()
        return job_id

    def append_text(self, job_id: str | None, text: str) -> None:
        """追加文本片段。"""
        if not job_id or not text.strip():
            return
        job = self._jobs_by_id.get(job_id)
        if job is None or job.cancelled:
            return
        job.text_enqueued = True
        job.text_queue.put(text)

    def bind_generation(
        self,
        job_id: str | None,
        *,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        version_id: str,
    ) -> None:
        """将任务绑定到已持久化的 assistant version。"""
        if not job_id:
            return
        job = self._jobs_by_id.get(job_id)
        if job is None or job.cancelled:
            return

        job.user_id = user_id
        job.thread_id = thread_id
        job.assistant_message_id = assistant_message_id
        job.version_id = version_id
        with self._jobs_lock:
            self._jobs_by_version_id[version_id] = job

        status = "failed" if job.error_message else "generating"
        self._chat_store.upsert_speech_asset(
            user_id,
            thread_id,
            assistant_message_id,
            version_id,
            status=status,
            mime_type=job.mime_type,
            error_message=job.error_message,
        )
        if job.error_message is None and job.stream_completed:
            asyncio.create_task(self._finalize_generation(job))

    def finish_generation(self, job_id: str | None, fallback_text: str | None = None) -> None:
        """结束文本输入。"""
        if not job_id:
            return
        job = self._jobs_by_id.get(job_id)
        if job is None or job.cancelled or job.text_completed:
            return
        if fallback_text and not job.text_enqueued and fallback_text.strip():
            job.text_enqueued = True
            job.text_queue.put(fallback_text)
        job.text_completed = True
        job.text_queue.put(_JOB_SENTINEL)

    def cancel_generation(self, job_id: str | None) -> None:
        """取消未落库的语音任务。"""
        if not job_id:
            return
        job = self._jobs_by_id.get(job_id)
        if job is None:
            return
        job.cancelled = True
        if not job.text_completed:
            job.text_completed = True
            job.text_queue.put(_JOB_SENTINEL)
        self._cleanup_job(job)

    def build_playback_url(
        self,
        *,
        user_id: str,
        thread_id: str,
        assistant_message_id: str,
        version_id: str,
        base_url: str,
    ) -> tuple[str, str]:
        """生成播放地址和当前语音状态。"""
        asset = self._chat_store.get_speech_asset(user_id, thread_id, assistant_message_id, version_id)
        if asset is None:
            raise FileNotFoundError("Speech asset not found")
        if asset.status not in {"generating", "ready"}:
            raise RuntimeError(asset.error_message or "Speech asset unavailable")

        token = jwt.encode(
            {
                "purpose": "speech-playback",
                "sub": user_id,
                "thread_id": thread_id,
                "message_id": assistant_message_id,
                "version_id": version_id,
                "exp": _utc_now() + timedelta(seconds=_PLAYBACK_TOKEN_TTL_SECONDS),
                "iat": _utc_now(),
            },
            self._jwt_secret,
            algorithm="HS256",
        )
        playback_url = f"{base_url.rstrip('/')}/api/speech/play/{token}"
        return playback_url, asset.status

    def get_playback_target(self, token: str) -> SpeechPlaybackTarget:
        """根据播放 token 返回音频流。"""
        payload = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
        if payload.get("purpose") != "speech-playback":
            raise ValueError("Invalid speech playback token")

        user_id = str(payload["sub"])
        thread_id = str(payload["thread_id"])
        assistant_message_id = str(payload["message_id"])
        version_id = str(payload["version_id"])
        asset = self._chat_store.get_speech_asset(user_id, thread_id, assistant_message_id, version_id)
        if asset is None:
            raise FileNotFoundError("Speech asset not found")

        if asset.status == "generating":
            job = self._jobs_by_version_id.get(version_id)
            if job is None:
                raise RuntimeError("Speech stream unavailable")
            return SpeechPlaybackTarget(media_type=job.mime_type, iterator=self._iter_generating_audio(job))

        if asset.status != "ready" or not asset.object_key:
            raise RuntimeError(asset.error_message or "Speech asset unavailable")

        return SpeechPlaybackTarget(
            media_type=asset.mime_type or _DEFAULT_SPEECH_MIME_TYPE,
            iterator=self._object_store.iter_file(asset.object_key),
        )

    def _run_generation_worker(self, job: SpeechGenerationJob) -> None:
        try:
            runner = self._create_runner(job)
        except Exception as exc:  # pragma: no cover - depends on runtime env
            job.mark_failed(str(exc))
            return

        try:
            while True:
                item = job.text_queue.get()
                if item is _JOB_SENTINEL:
                    break
                if not isinstance(item, str) or not item.strip():
                    continue
                runner.streaming_call(item)
            if job.cancelled:
                return
            if job.text_enqueued:
                runner.streaming_complete()
            else:
                job.mark_failed("No speech content available")
        except Exception as exc:  # pragma: no cover - network/runtime boundary
            job.mark_failed(str(exc))

    def _create_runner(self, job: SpeechGenerationJob):
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

        service = self

        class _Callback(ResultCallback):
            def __init__(self) -> None:
                self._file_handle = job.spool_path.open("ab")

            def on_open(self) -> None:
                return None

            def on_complete(self) -> None:
                self._file_handle.flush()
                self._file_handle.close()
                job.mark_stream_completed()
                if job.version_id is not None and not job.error_message:
                    job.loop.call_soon_threadsafe(lambda: asyncio.create_task(service._finalize_generation(job)))

            def on_error(self, message: str) -> None:
                if not self._file_handle.closed:
                    self._file_handle.flush()
                    self._file_handle.close()
                job.mark_failed(message)
                if job.version_id is not None:
                    job.loop.call_soon_threadsafe(lambda: asyncio.create_task(service._mark_generation_failed(job)))

            def on_close(self) -> None:
                if not self._file_handle.closed:
                    self._file_handle.flush()
                    self._file_handle.close()

            def on_event(self, message):  # pragma: no cover - debug hook
                del message

            def on_data(self, data: bytes) -> None:
                self._file_handle.write(data)
                self._file_handle.flush()
                job.mark_audio_chunk(len(data))

        dashscope.api_key = self._tts_api_key
        dashscope.base_websocket_api_url = self._tts_ws_url
        callback = _Callback()
        return SpeechSynthesizer(
            model=self._tts_model,
            voice=self._tts_voice,
            format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
            callback=callback,
        )

    async def _mark_generation_failed(self, job: SpeechGenerationJob) -> None:
        if job.version_id is None or job.assistant_message_id is None:
            return
        self._chat_store.upsert_speech_asset(
            job.user_id,
            job.thread_id,
            job.assistant_message_id,
            job.version_id,
            status="failed",
            mime_type=job.mime_type,
            error_message=job.error_message,
        )
        self._cleanup_job(job)

    async def _finalize_generation(self, job: SpeechGenerationJob) -> None:
        if job.version_id is None or job.assistant_message_id is None or job.error_message:
            return
        with job.lock:
            if job.finalize_started:
                return
            job.finalize_started = True

        object_key = (
            f"threads/{job.thread_id}/messages/{job.assistant_message_id}/versions/{job.version_id}.mp3"
        )
        try:
            await self._object_store.put_file(job.spool_path, object_key, job.mime_type)
        except Exception as exc:  # pragma: no cover - object storage boundary
            job.mark_failed(str(exc))
            await self._mark_generation_failed(job)
            return

        job.object_key = object_key
        self._chat_store.upsert_speech_asset(
            job.user_id,
            job.thread_id,
            job.assistant_message_id,
            job.version_id,
            status="ready",
            mime_type=job.mime_type,
            object_key=object_key,
            error_message=None,
        )

        if job.active_readers == 0:
            self._cleanup_job(job)
        else:
            job.cleanup_requested = True

    async def _iter_generating_audio(self, job: SpeechGenerationJob, chunk_size: int = 65536) -> AsyncIterator[bytes]:
        with job.lock:
            job.active_readers += 1

        file_handle = None
        try:
            while not job.spool_path.exists():
                if job.failed_event.is_set() or job.completed_event.is_set():
                    return
                await self._wait_for_job_update(job)
                job.update_event.clear()

            file_handle = job.spool_path.open("rb")
            while True:
                chunk = await asyncio.to_thread(file_handle.read, chunk_size)
                if chunk:
                    yield chunk
                    continue

                if job.failed_event.is_set() or job.completed_event.is_set():
                    break

                await self._wait_for_job_update(job)
                job.update_event.clear()
        finally:
            if file_handle is not None:
                file_handle.close()
            with job.lock:
                job.active_readers = max(0, job.active_readers - 1)
                should_cleanup = job.cleanup_requested and job.active_readers == 0
            if should_cleanup:
                self._cleanup_job(job)

    async def _wait_for_job_update(self, job: SpeechGenerationJob) -> None:
        try:
            await asyncio.wait_for(job.update_event.wait(), timeout=1.0)
        except TimeoutError:
            return

    def _cleanup_job(self, job: SpeechGenerationJob) -> None:
        with job.lock:
            if job.cleanup_done:
                return
            job.cleanup_done = True

        with self._jobs_lock:
            self._jobs_by_id.pop(job.id, None)
            if job.version_id is not None:
                self._jobs_by_version_id.pop(job.version_id, None)

        if job.spool_path.exists():
            try:
                job.spool_path.unlink()
            except OSError:
                pass
