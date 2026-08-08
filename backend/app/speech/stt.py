"""千问实时语音识别（Paraformer Realtime）双向流式会话封装。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "paraformer-realtime-v2"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def stt_api_key() -> str:
    """ASR API Key：优先 ALIYUN_STT_API_KEY，其次 TTS Key，最后回退 LLM 的百炼 Key。"""
    return _env("ALIYUN_STT_API_KEY", _env("ALIYUN_TTS_API_KEY", _env("OPENAI_API_KEY")))


def stt_ws_url() -> str:
    return _env("ALIYUN_STT_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")


def stt_model() -> str:
    return _env("ALIYUN_STT_MODEL", DEFAULT_MODEL)


class DashScopeSttSession:
    """一次按住说话的识别会话。

    DashScope 回调在 SDK 工作线程触发，事件统一通过 asyncio.Queue 交给
    调用方协程消费（线程安全：经 event loop 的 call_soon_threadsafe 入队）。
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
        self._recognizer: Any = None
        self._started = False
        self._final_text = ""
        self._latest_text = ""

    @property
    def ready(self) -> bool:
        return self._started

    def _enqueue(self, event: dict[str, Any]) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        else:  # pragma: no cover - 关闭窗口期的兜底
            _LOGGER.warning("STT event loop closed, dropping event %s", event.get("type"))

    def _on_event(self, result: Any) -> None:
        """SDK 回调：result-generated。"""
        try:
            sentence = result.get_sentence()
            is_end = bool(result.is_sentence_end())
        except Exception:  # noqa: BLE001 - 解析失败丢弃该帧
            _LOGGER.exception("STT parse result failed")
            return
        text = ""
        if isinstance(sentence, dict):
            text = str(sentence.get("text", ""))
        elif isinstance(sentence, list):
            text = "".join(str(item.get("text", "")) for item in sentence if isinstance(item, dict))
        clean_text = text.strip()
        if clean_text:
            self._latest_text = clean_text
            if is_end:
                self._final_text = clean_text
        self._enqueue({"type": "sentence", "text": text, "sentence_end": is_end})

    def _on_complete(self) -> None:
        text = self._final_text or self._latest_text
        self._enqueue({"type": "done", "text": text})

    def _on_error(self, result: Any) -> None:
        message = str(getattr(result, "message", None) or result)
        self._enqueue({"type": "error", "message": message})

    def _on_close(self) -> None:
        self._enqueue({"type": "closed"})

    def start(self) -> bool:
        """建立连接并启动识别任务（SDK 自行管理后台线程，此处不阻塞）。

        返回是否成功开始。事件（ready/sentence/done/error/closed）进入 events()。
        """
        if self._started:
            return True
        if not self._api_key:
            self._enqueue({"type": "error", "message": "STT API Key 未配置"})
            return False
        try:
            import dashscope
            from dashscope.audio.asr import Recognition, RecognitionCallback

            self._loop = asyncio.get_running_loop()
            dashscope.api_key = self._api_key
            dashscope.base_websocket_api_url = stt_ws_url()

            class _Callback(RecognitionCallback):
                def __init__(self, session: "DashScopeSttSession") -> None:
                    self._session = session

                def on_open(self) -> None:
                    self._session._enqueue({"type": "ready"})

                def on_event(self, result: Any) -> None:
                    self._session._on_event(result)

                def on_complete(self) -> None:
                    self._session._on_complete()

                def on_error(self, result: Any) -> None:
                    self._session._on_error(result)

                def on_close(self) -> None:
                    self._session._on_close()

            self._recognizer = Recognition(
                model=self._model,
                callback=_Callback(self),
                format=self._format,
                sample_rate=self._sample_rate,
                language_hints=self._language_hints,
                disfluency_removal_enabled=True,
            )
            self._recognizer.start()
            self._started = True
            _LOGGER.info("STT session started: model=%s", self._model)
            return True
        except Exception:  # noqa: BLE001 - 连接失败统一按未启动处理
            _LOGGER.exception("STT session start failed")
            self._enqueue({"type": "error", "message": "STT 连接失败"})
            return False

    def send_audio_frame(self, data: bytes) -> None:
        if self._recognizer is not None:
            self._recognizer.send_audio_frame(data)

    def finish(self) -> None:
        """结束识别：阻塞等待 SDK 输出完整结果后关闭连接。"""
        if self._recognizer is None:
            return
        recognizer, self._recognizer = self._recognizer, None
        try:
            recognizer.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("STT session stop failed")
        self._started = False

    async def events(self) -> dict[str, Any]:
        """等待并返回下一个事件（协程消费端）。"""
        return await self._queue.get()
