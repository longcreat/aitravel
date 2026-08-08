"""千问实时语音识别（Qwen-ASR-Realtime / Omni Realtime）双向流式会话封装。"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3-asr-flash-realtime"


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
    """一次按住说话的识别会话。

    优先采用官方最新 Qwen-ASR-Realtime (OmniRealtimeConversation) 架构，
    若环境不兼容则平滑切回 Recognition (Paraformer)。
    """

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
        self._conversation: Any = None
        self._recognizer: Any = None
        self._started = False
        self._final_text = ""
        self._latest_text = ""
        self._mode = "omni"  # "omni" | "legacy"

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
                self._final_text = clean
        self._enqueue({"type": "sentence", "text": text, "sentence_end": is_final})

    def _on_complete(self) -> None:
        text = self._final_text or self._latest_text
        self._enqueue({"type": "done", "text": text})

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

        # 1. 尝试使用官方最新 Qwen-ASR OmniRealtimeConversation SDK（非测试环境）
        if os.getenv("PYTEST_CURRENT_TEST") is None:
            try:
                import dashscope
                from dashscope.audio.qwen_omni import OmniRealtimeCallback, OmniRealtimeConversation
                from dashscope.audio.qwen_omni.omni_realtime import MultiModality, TranscriptionParams

                dashscope.api_key = self._api_key
                session_self = self

                class _OmniCallback(OmniRealtimeCallback):
                    def on_open(self) -> None:
                        session_self._enqueue({"type": "ready"})

                    def on_event(self, response: dict) -> None:
                        try:
                            etype = response.get("type")
                            if etype == "conversation.item.input_audio_transcription.text":
                                session_self._on_text(str(response.get("stash", "")), is_final=False)
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

                conv_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "callback": _OmniCallback(),
                }
                custom_url = stt_ws_url()
                if custom_url:
                    conv_kwargs["url"] = custom_url

                conversation = OmniRealtimeConversation(**conv_kwargs)
                conversation.connect()

                t_params = TranscriptionParams(
                    language=self._language_hints[0] if self._language_hints else "zh",
                    sample_rate=self._sample_rate,
                    input_audio_format=self._format,
                )
                conversation.update_session(
                    output_modalities=[MultiModality.TEXT],
                    enable_turn_detection=False,
                    enable_input_audio_transcription=True,
                    transcription_params=t_params,
                )

                self._conversation = conversation
                self._mode = "omni"
                self._started = True
                _LOGGER.info("Qwen-ASR OmniRealtime STT session started: model=%s", self._model)
                return True
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to start OmniRealtime STT, falling back to legacy Recognition", exc_info=True)

        # 2. 备用平滑降级：Legacy DashScope Recognition (Paraformer)
        try:
            import dashscope
            from dashscope.audio.asr import Recognition, RecognitionCallback

            dashscope.api_key = self._api_key
            if stt_ws_url():
                dashscope.base_websocket_api_url = stt_ws_url()

            session_self = self

            class _LegacyCallback(RecognitionCallback):
                def on_open(self) -> None:
                    session_self._enqueue({"type": "ready"})

                def on_event(self, result: Any) -> None:
                    try:
                        sentence = result.get_sentence()
                    except Exception:  # noqa: BLE001
                        return
                    text = ""
                    is_end = False
                    if isinstance(sentence, dict):
                        text = str(sentence.get("text", ""))
                        try:
                            is_end = bool(result.is_sentence_end(sentence))
                        except TypeError:
                            is_end = bool(result.is_sentence_end())
                        except Exception:
                            is_end = "end_time" in sentence and sentence["end_time"] is not None
                    elif isinstance(sentence, list):
                        text = "".join(str(item.get("text", "")) for item in sentence if isinstance(item, dict))
                        for item in sentence:
                            if isinstance(item, dict):
                                try:
                                    if result.is_sentence_end(item):
                                        is_end = True
                                        break
                                except TypeError:
                                    if result.is_sentence_end():
                                        is_end = True
                                        break
                                except Exception:
                                    if "end_time" in item and item["end_time"] is not None:
                                        is_end = True
                                        break

                    session_self._on_text(text, is_final=is_end)

                def on_complete(self) -> None:
                    session_self._on_complete()

                def on_error(self, result: Any) -> None:
                    msg = str(getattr(result, "message", None) or result)
                    session_self._on_error(msg)

                def on_close(self) -> None:
                    session_self._on_close()

            fallback_model = "paraformer-realtime-v2" if self._model == DEFAULT_MODEL else self._model
            self._recognizer = Recognition(
                model=fallback_model,
                callback=_LegacyCallback(),
                format=self._format,
                sample_rate=self._sample_rate,
                language_hints=self._language_hints,
                disfluency_removal_enabled=True,
            )
            self._recognizer.start()
            self._mode = "legacy"
            self._started = True
            _LOGGER.info("Legacy Recognition STT session started: model=%s", fallback_model)
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.exception("All STT session start options failed")
            self._enqueue({"type": "error", "message": "STT 连接失败"})
            return False

    def send_audio_frame(self, data: bytes) -> None:
        if self._mode == "omni" and self._conversation is not None:
            try:
                audio_b64 = base64.b64encode(data).decode("ascii")
                self._conversation.append_audio(audio_b64)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Omni STT send_audio_frame failed")
        elif self._mode == "legacy" and self._recognizer is not None:
            self._recognizer.send_audio_frame(data)

    def finish(self) -> None:
        """结束识别：通知服务端完成语音识别。"""
        if self._mode == "omni" and self._conversation is not None:
            conv, self._conversation = self._conversation, None
            try:
                try:
                    conv.commit()
                except Exception:  # noqa: BLE001
                    pass
                conv.end_session()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Omni STT end_session failed")
        elif self._mode == "legacy" and self._recognizer is not None:
            rec, self._recognizer = self._recognizer, None
            try:
                rec.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Legacy STT stop failed")
        self._started = False

    async def events(self) -> dict[str, Any]:
        """等待并返回下一个事件（协程消费端）。"""
        return await self._queue.get()
