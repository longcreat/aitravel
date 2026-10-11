"""千问实时语音识别（Qwen-ASR-Realtime / Omni Realtime）会话封装。

协议实证结论（对照官方文档 + 实测，2026-09）：
- Manual 模式（enable_turn_detection=False）是官方为"聊天软件按住说话"设计的模式；
  录音期间 partial（text+stash）照常流式推送，commit 触发最终 transcript（实测 ~150ms）。
- session.finished 在最后一次活动后 ~6s 才由服务端下发，因此结束会话不能同步等待它
  （会白白阻塞 5s+），应在拿到最终 transcript 后直接 close。
- 每段 transcript 由 conversation.item.input_audio_transcription.completed 下发，
  多段时必须累积拼接，不能覆盖。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
from typing import Any

import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeCallback, OmniRealtimeConversation
from dashscope.audio.qwen_omni.omni_realtime import MultiModality, TranscriptionParams

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3-asr-flash-realtime"
# commit 后等待最终 transcript 的上限（实测 ~150ms 到达）
_FINAL_RESULT_WAIT_S = 2.5


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def stt_api_key() -> str:
    """ASR API Key：优先 ALIYUN_STT_API_KEY，其次 TTS Key，最后回退 LLM 的百炼 Key。"""
    return _env("ALIYUN_STT_API_KEY", _env("ALIYUN_TTS_API_KEY", _env("OPENAI_API_KEY")))


def stt_ws_url() -> str:
    return _env("ALIYUN_STT_WS_URL", "")


def stt_model() -> str:
    return _env("ALIYUN_STT_MODEL", DEFAULT_MODEL)


class DashScopeSttSession:
    """一次按住说话的识别会话。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        sample_rate: int = 16000,
        format: str = "pcm",
        language_hints: list[str] | None = None,
    ) -> None:
        self._api_key = api_key or stt_api_key()
        self._model = model or stt_model()
        self._sample_rate = sample_rate
        self._format = format
        self._language_hints = language_hints or ["zh"]
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._conversation: OmniRealtimeConversation | None = None
        self._started = False
        self._final_parts: list[str] = []
        self._latest_text = ""
        self._finishing = False
        self._done_sent = False
        self._final_event = threading.Event()

    @property
    def ready(self) -> bool:
        return self._started

    def _enqueue(self, event: dict[str, Any]) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        else:  # pragma: no cover - 关闭窗口期的兜底
            _LOGGER.warning("STT event loop closed, dropping event %s", event.get("type"))

    def _on_text(self, text: str, is_final: bool = False) -> None:
        clean = text.strip()
        if clean:
            self._latest_text = clean
            if is_final:
                # 多段识别（多次 commit）时累积拼接，不能覆盖
                self._final_parts.append(clean)
                self._final_event.set()
        self._enqueue({"type": "sentence", "text": text, "sentence_end": is_final})
        # 最终句（.completed）必定先于 session.finished 到达；松手后直接交付，
        # 不必再等服务端 session.finished，大幅降低松手后的等待延迟。
        if is_final and self._finishing:
            self._emit_done()

    def _final_transcript(self) -> str:
        return "".join(self._final_parts)

    def _emit_done(self) -> None:
        if self._done_sent:
            return
        self._done_sent = True
        text = self._final_transcript() or self._latest_text
        self._enqueue({"type": "done", "text": text})

    def _on_complete(self) -> None:
        self._emit_done()

    def _on_error(self, message: str) -> None:
        self._enqueue({"type": "error", "message": message})

    def _on_close(self) -> None:
        self._enqueue({"type": "closed"})

    def start(self) -> bool:
        if self._started:
            return True
        if not self._api_key:
            self._enqueue({"type": "error", "message": "STT API Key 未配置"})
            return False

        self._loop = asyncio.get_running_loop()
        try:
            dashscope.api_key = self._api_key
            session_self = self

            class _OmniCallback(OmniRealtimeCallback):
                def on_open(self) -> None:
                    session_self._enqueue({"type": "ready"})

                def on_event(self, response: dict) -> None:
                    try:
                        etype = response.get("type")
                        if etype == "conversation.item.input_audio_transcription.text":
                            # 官方协议：已确认前缀 text + 临时草稿 stash，实时预览必须拼接两者
                            confirmed = str(response.get("text", "") or "")
                            stash = str(response.get("stash", "") or "")
                            session_self._on_text(confirmed + stash, is_final=False)
                        elif etype == "conversation.item.input_audio_transcription.completed":
                            session_self._on_text(str(response.get("transcript", "")), is_final=True)
                        elif etype == "session.finished":
                            session_self._on_complete()
                        elif etype == "error":
                            err_msg = str(response.get("error", {}).get("message", "识别出错"))
                            session_self._on_error(err_msg)
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("STT parse omni event failed")

                def on_close(self, close_status_code: Any, close_msg: Any) -> None:
                    session_self._on_close()

            conv_kwargs: dict[str, Any] = {"model": self._model, "callback": _OmniCallback()}
            custom_url = stt_ws_url()
            if custom_url:
                conv_kwargs["url"] = custom_url

            conversation = OmniRealtimeConversation(**conv_kwargs)
            conversation.connect()
            conversation.update_session(
                output_modalities=[MultiModality.TEXT],
                enable_turn_detection=False,
                enable_input_audio_transcription=True,
                transcription_params=TranscriptionParams(
                    language=self._language_hints[0] if self._language_hints else "zh",
                    sample_rate=self._sample_rate,
                    input_audio_format=self._format,
                ),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("OmniRealtime STT session start failed")
            self._enqueue({"type": "error", "message": "STT 连接失败"})
            return False

        self._conversation = conversation
        self._started = True
        _LOGGER.info("Qwen-ASR OmniRealtime STT session started: model=%s", self._model)
        return True

    def send_audio_frame(self, data: bytes) -> None:
        if self._conversation is None:
            return
        try:
            self._conversation.append_audio(base64.b64encode(data).decode("ascii"))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omni STT send_audio_frame failed")

    def finish(self) -> None:
        """结束识别：commit 触发服务端产出最终 transcript，拿到后立即关闭。"""
        self._finishing = True
        conversation, self._conversation = self._conversation, None
        if conversation is None:
            return
        try:
            try:
                conversation.commit()
            except Exception:  # noqa: BLE001
                pass
            # .completed 通常在 commit 后 ~150ms 到达；最多等 _FINAL_RESULT_WAIT_S
            self._final_event.wait(_FINAL_RESULT_WAIT_S)
            try:
                conversation.end_session_async()
            except Exception:  # noqa: BLE001
                pass
            conversation.close()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omni STT finish failed")
        self._started = False

    async def events(self) -> dict[str, Any]:
        """等待并返回下一个事件（协程消费端）。"""
        return await self._queue.get()
