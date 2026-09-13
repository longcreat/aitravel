import { useCallback, useEffect, useRef, useState } from "react";

import { getStoredAccessToken } from "@/features/auth/model/auth.storage";
import { resolveApiUrl } from "@/shared/config/env";

const TARGET_SAMPLE_RATE = 16000;
const AUDIO_CONTEXT_OPTIONS = { audio: { echoCancellation: true, noiseSuppression: true } };
/** 松手后等待最终转写结果的兜底超时；超时用已识别的部分文本交付 */
const RESOLVE_TIMEOUT_MS = 5000;

export type VoiceStatus = "idle" | "starting" | "recording";

export interface VoiceInputOptions {
  /** 松手即触发：聊天区挂转写等待气泡 */
  onUtteranceStarted: (id: string) => void;
  /** 转写完成（含超时部分文本兜底），文本进入发送队列 */
  onUtteranceResolved: (id: string, text: string) => void;
  /** 未识别到内容（message 为 null，静默）或识别失败（message 非空，提示用户） */
  onUtteranceFailed: (id: string, message: string | null) => void;
}

export interface VoiceInput {
  status: VoiceStatus;
  interimText: string;
  error: string | null;
  press: () => void;
  release: () => void;
  cancel: () => void;
}

interface VoiceSession {
  id: string;
  socket: WebSocket | null;
  context: AudioContext | null;
  source: MediaStreamAudioSourceNode | null;
  processor: ScriptProcessorNode | null;
  stream: MediaStream | null;
  pendingAudio: ArrayBuffer[];
  finishRequested: boolean;
  finishSent: boolean;
  interimText: string;
  finalText: string;
  released: boolean;
  settled: boolean;
  resolveTimer: number | null;
}

function resolveVoiceWsUrl(): string {
  const api = resolveApiUrl("/api/stt/ws");
  if (api.startsWith("http")) {
    return api.replace(/^http/, "ws");
  }
  const origin = `${window.location.protocol}//${window.location.host}`;
  return `${origin.replace(/^http/, "ws")}${api}`;
}

function pcm16Encode(chunk: Float32Array, sampleRate: number): ArrayBuffer {
  const step = sampleRate / TARGET_SAMPLE_RATE;
  const outLen = Math.max(1, Math.floor(chunk.length / step));
  const output = new ArrayBuffer(outLen * 2);
  const view = new DataView(output);
  for (let i = 0; i < outLen; i += 1) {
    let sample = chunk[Math.min(chunk.length - 1, Math.floor(i * step))];
    sample = Math.max(-1, Math.min(1, sample));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return output;
}

function createSession(): VoiceSession {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `utt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    id,
    socket: null,
    context: null,
    source: null,
    processor: null,
    stream: null,
    pendingAudio: [],
    finishRequested: false,
    finishSent: false,
    interimText: "",
    finalText: "",
    released: false,
    settled: false,
    resolveTimer: null,
  };
}

function partialText(session: VoiceSession): string {
  // finalText 是已完成的段落累积，interimText 是当前段未完成的草稿，拼接兜底
  return (session.finalText + session.interimText).trim();
}

export function useVoiceInput(options: VoiceInputOptions): VoiceInput {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [interimText, setInterimText] = useState("");
  const [error, setError] = useState<string | null>(null);

  // 回调经 ref 分发：会话生命周期长于渲染，杜绝陈旧闭包
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const currentRef = useRef<VoiceSession | null>(null);
  const inflightRef = useRef<Map<string, VoiceSession>>(new Map());

  const teardownSession = useCallback((session: VoiceSession) => {
    if (session.resolveTimer !== null) {
      window.clearTimeout(session.resolveTimer);
      session.resolveTimer = null;
    }
    const socket = session.socket;
    session.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      try {
        socket.close();
      } catch {
        // 已关闭
      }
    }
    const processor = session.processor;
    session.processor = null;
    if (processor) {
      processor.onaudioprocess = null;
      processor.disconnect();
    }
    const source = session.source;
    session.source = null;
    if (source) {
      source.disconnect();
    }
    const context = session.context;
    session.context = null;
    if (context && context.state !== "closed") {
      void context.close();
    }
    const stream = session.stream;
    session.stream = null;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  }, []);

  const settleSession = useCallback(
    (session: VoiceSession, outcome: { ok: true; text: string } | { ok: false; message: string | null }) => {
      if (session.settled) {
        return;
      }
      session.settled = true;
      inflightRef.current.delete(session.id);
      teardownSession(session);
      if (outcome.ok) {
        optionsRef.current.onUtteranceResolved(session.id, outcome.text);
      } else {
        optionsRef.current.onUtteranceFailed(session.id, outcome.message);
      }
    },
    [teardownSession],
  );

  /** 录音中（尚未松手）出错：输入条内联报错，不产生话语回调 */
  const failActive = useCallback(
    (session: VoiceSession, message: string) => {
      if (session.settled) {
        return;
      }
      session.settled = true;
      if (currentRef.current === session) {
        currentRef.current = null;
        setStatus("idle");
        setInterimText("");
        setError(message);
      }
      teardownSession(session);
    },
    [teardownSession],
  );

  /** 统一错误出口：已松手的会话优先用已识别的部分文本兜底，完全没有才判失败 */
  const abortWithError = useCallback(
    (session: VoiceSession, message: string) => {
      if (session.settled) {
        return;
      }
      if (session.released) {
        const text = partialText(session);
        if (text) {
          settleSession(session, { ok: true, text });
        } else {
          settleSession(session, { ok: false, message });
        }
      } else {
        failActive(session, message);
      }
    },
    [failActive, settleSession],
  );

  const sendFinish = useCallback(
    (session: VoiceSession) => {
      if (session.finishSent || session.settled) {
        return;
      }
      session.finishRequested = true;
      const socket = session.socket;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return; // onopen 后补发
      }
      session.finishSent = true;
      try {
        socket.send(JSON.stringify({ action: "finish" }));
      } catch {
        abortWithError(session, "语音识别连接已断开");
        return;
      }
      session.resolveTimer = window.setTimeout(() => {
        const text = partialText(session);
        if (text) {
          settleSession(session, { ok: true, text });
        } else {
          settleSession(session, { ok: false, message: "语音识别超时，请重试" });
        }
      }, RESOLVE_TIMEOUT_MS);
    },
    [abortWithError, settleSession],
  );

  const flushAudio = useCallback((session: VoiceSession) => {
    const socket = session.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN || session.pendingAudio.length === 0) {
      return;
    }
    const frames = session.pendingAudio;
    session.pendingAudio = [];
    for (const frame of frames) {
      try {
        socket.send(frame);
      } catch {
        break;
      }
    }
  }, []);

  const handleSessionMessage = useCallback(
    (session: VoiceSession, raw: unknown) => {
      if (session.settled) {
        return;
      }
      let message: { type?: string; text?: string; sentence_end?: boolean; message?: string };
      try {
        message = JSON.parse(String(raw));
      } catch {
        return;
      }
      if (message.type === "sentence") {
        const text = String(message.text ?? "");
        if (message.sentence_end) {
          const clean = text.trim();
          if (clean) {
            // 多段识别时累积拼接（VAD 断句/多次 commit），不能覆盖
            session.finalText += clean;
            session.interimText = "";
          }
          // 松手后的最终句（.completed）已含完整结果，直接结算，不等 done
          if (session.released) {
            if (session.finalText) {
              settleSession(session, { ok: true, text: session.finalText });
            } else {
              settleSession(session, { ok: false, message: null });
            }
          }
        } else if (text.trim()) {
          session.interimText = text.trim();
          // 只有正在录音的会话才驱动输入条；后台转写会话不上屏
          if (currentRef.current === session) {
            setInterimText(text);
          }
        }
      } else if (message.type === "done") {
        const text = String(message.text ?? "").trim() || partialText(session);
        if (text) {
          settleSession(session, { ok: true, text });
        } else {
          settleSession(session, { ok: false, message: null });
        }
      } else if (message.type === "error") {
        abortWithError(session, String(message.message ?? "语音识别失败"));
      }
    },
    [abortWithError, settleSession],
  );

  const openAudioPipeline = useCallback(
    async (session: VoiceSession) => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONTEXT_OPTIONS);
        if (session.settled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        session.stream = stream;
        const AudioContextCtor =
          window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioContextCtor) {
          failActive(session, "当前浏览器不支持录音");
          return;
        }
        let context: AudioContext;
        try {
          // 让浏览器原生重采样到 16kHz（自带抗混叠滤波）；旧环境不支持时退回
          // 默认采样率 + JS 隔点抽取。手工降采样没有低通，高频会折叠成噪声，
          // 实测会明显损伤识别准确率（丢字/错字）。
          context = new AudioContextCtor({ sampleRate: TARGET_SAMPLE_RATE });
        } catch {
          context = new AudioContextCtor();
        }
        session.context = context;
        if (context.state === "suspended") {
          // iOS 等浏览器在非手势栈中创建的上下文可能处于 suspended，不会出音频
          try {
            await context.resume();
          } catch {
            // 继续走下面的 running 校验
          }
        }
        if (context.state !== "running") {
          failActive(session, "麦克风初始化失败，请重试");
          return;
        }
        const source = context.createMediaStreamSource(stream);
        session.source = source;
        const processor = context.createScriptProcessor(1024, 1, 1);
        session.processor = processor;
        processor.onaudioprocess = (event) => {
          if (session.settled) {
            return;
          }
          const pcm = pcm16Encode(event.inputBuffer.getChannelData(0), context.sampleRate);
          const socket = session.socket;
          if (socket && socket.readyState === WebSocket.OPEN) {
            flushAudio(session);
            try {
              socket.send(pcm);
            } catch {
              // 断连由 onclose 统一处理
            }
          } else {
            // 暂存建连前的 PCM 帧，防止丢失前半段语音
            session.pendingAudio.push(pcm);
          }
        };
        source.connect(processor);
        processor.connect(context.destination);
        if (currentRef.current === session) {
          setStatus("recording");
        }
        if (session.released) {
          // 极快点击：松手时管线尚未就绪，就绪后立即补发 finish
          flushAudio(session);
          sendFinish(session);
        }
      } catch {
        abortWithError(session, "无法访问麦克风，请检查浏览器权限");
      }
    },
    [abortWithError, flushAudio, sendFinish],
  );

  const press = useCallback(() => {
    if (currentRef.current) {
      return;
    }
    const token = getStoredAccessToken();
    if (!token) {
      setError("请先登录后再使用语音输入");
      return;
    }
    setError(null);
    setInterimText("");

    const session = createSession();
    let socket: WebSocket;
    try {
      socket = new WebSocket(`${resolveVoiceWsUrl()}?token=${encodeURIComponent(token)}`);
    } catch {
      setError("无法连接语音识别服务");
      return;
    }
    session.socket = socket;
    socket.onopen = () => {
      if (session.settled) {
        return;
      }
      flushAudio(session);
      if (session.finishRequested) {
        sendFinish(session);
      }
    };
    socket.onmessage = (event) => {
      handleSessionMessage(session, event.data);
    };
    const onDead = () => {
      abortWithError(session, "语音识别连接已断开");
    };
    socket.onclose = onDead;
    socket.onerror = onDead;

    currentRef.current = session;
    setStatus("starting");
    void openAudioPipeline(session);
  }, [abortWithError, flushAudio, handleSessionMessage, openAudioPipeline, sendFinish]);

  const release = useCallback(() => {
    const session = currentRef.current;
    if (!session || session.settled) {
      return;
    }
    currentRef.current = null;
    session.released = true;
    // 输入条立即复位，可马上开始下一句；转写转后台会话
    setStatus("idle");
    setInterimText("");
    inflightRef.current.set(session.id, session);
    optionsRef.current.onUtteranceStarted(session.id);
    sendFinish(session);
  }, [sendFinish]);

  const cancel = useCallback(() => {
    const session = currentRef.current;
    if (session && !session.settled) {
      session.settled = true; // 静默丢弃，不触发任何话语回调
      teardownSession(session);
    }
    currentRef.current = null;
    setStatus("idle");
    setInterimText("");
    setError(null);
  }, [teardownSession]);

  // 卸载：终止全部会话（含后台转写），静默丢弃
  useEffect(() => {
    return () => {
      const current = currentRef.current;
      currentRef.current = null;
      if (current && !current.settled) {
        current.settled = true;
        teardownSession(current);
      }
      for (const session of inflightRef.current.values()) {
        session.settled = true;
        teardownSession(session);
      }
      inflightRef.current.clear();
    };
  }, [teardownSession]);

  return { status, interimText, error, press, release, cancel };
}
