import { useCallback, useRef, useState } from "react";

import { getStoredAccessToken } from "@/features/auth/model/auth.storage";
import { resolveApiUrl } from "@/shared/config/env";

const TARGET_SAMPLE_RATE = 16000;
const AUDIO_CONTEXT_OPTIONS = { audio: { echoCancellation: true, noiseSuppression: true } };
const DONE_TIMEOUT_MS = 8000;

function resolveSttWsUrl(): string {
  const api = resolveApiUrl("/api/stt/ws");
  if (api.startsWith("http")) {
    return api.replace(/^http/, "ws");
  }
  const origin = `${window.location.protocol}//${window.location.host}`;
  return `${origin.replace(/^http/, "ws")}${api}`;
}

function pcm16Encode(chunk: Float32Array, sampleRate: number): ArrayBuffer {
  const output = new ArrayBuffer(chunk.length * 2);
  const view = new DataView(output);
  const step = sampleRate / TARGET_SAMPLE_RATE;
  for (let i = 0; i < chunk.length; i += 1) {
    let sample = chunk[Math.min(chunk.length - 1, Math.floor(i * step))];
    sample = Math.max(-1, Math.min(1, sample));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return output;
}

interface PushToTalkOptions {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onError: (message: string) => void;
}

export interface PushToTalk {
  recording: boolean;
  interimText: string;
  error: string | null;
  start: () => void;
  finish: () => void;
  cancel: () => void;
}

export function usePushToTalk({ onInterim, onFinal, onError }: PushToTalkOptions): PushToTalk {
  const [recording, setRecording] = useState(false);
  const [interimText, setInterimText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const doneTimerRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    if (doneTimerRef.current !== null) {
      window.clearTimeout(doneTimerRef.current);
      doneTimerRef.current = null;
    }
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      try {
        ws.close();
      } catch {
        // 已关闭
      }
    }
    const processor = processorRef.current;
    processorRef.current = null;
    if (processor) {
      processor.disconnect();
    }
    const source = sourceRef.current;
    sourceRef.current = null;
    if (source) {
      source.disconnect();
    }
    const context = contextRef.current;
    contextRef.current = null;
    if (context && context.state !== "closed") {
      void context.close();
    }
    const stream = streamRef.current;
    streamRef.current = null;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  }, []);

  const fail = useCallback(
    (message: string) => {
      cleanup();
      setRecording(false);
      setInterimText("");
      setError(message);
      onError(message);
    },
    [cleanup, onError],
  );

  const start = useCallback(() => {
    if (recording) {
      return;
    }
    setError(null);
    setInterimText("");

    const token = getStoredAccessToken();
    if (!token) {
      fail("请先登录后再使用语音输入");
      return;
    }

    let socket: WebSocket;
    let audioContext: AudioContext | null = null;
    let stream: MediaStream | null = null;
    try {
      socket = new WebSocket(`${resolveSttWsUrl()}?token=${encodeURIComponent(token)}`);
    } catch {
      fail("无法连接语音识别服务");
      return;
    }
    wsRef.current = socket;
    socket.onclose = () => {
      if (wsRef.current === socket) {
        setRecording(false);
      }
    };
    socket.onerror = () => {
      fail("语音识别连接异常");
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as {
          type: string;
          text?: string;
          sentence_end?: boolean;
          message?: string;
        };
        if (message.type === "sentence") {
          setInterimText(message.text ?? "");
          if (message.text) {
            onInterim(message.text);
          }
        } else if (message.type === "done") {
          if (doneTimerRef.current !== null) {
            window.clearTimeout(doneTimerRef.current);
            doneTimerRef.current = null;
          }
          cleanup();
          setRecording(false);
          setInterimText("");
          const text = (message.text ?? "").trim();
          if (text) {
            onFinal(text);
          }
        } else if (message.type === "error") {
          fail(message.message ?? "语音识别失败");
        }
      } catch {
        // 忽略无法解析的消息
      }
    };

    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONTEXT_OPTIONS);
        streamRef.current = stream;
        const AudioContextCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioContextCtor) {
          fail("当前浏览器不支持录音");
          return;
        }
        audioContext = new AudioContextCtor();
        contextRef.current = audioContext;
        const source = audioContext.createMediaStreamSource(stream);
        sourceRef.current = source;
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        processorRef.current = processor;
        processor.onaudioprocess = (event) => {
          const input = event.inputBuffer.getChannelData(0);
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && audioContext) {
            wsRef.current.send(pcm16Encode(input, audioContext.sampleRate));
          }
        };
        source.connect(processor);
        processor.connect(audioContext.destination);
        setRecording(true);
      } catch {
        fail("无法访问麦克风，请检查浏览器权限");
      }
    })();
  }, [cleanup, fail, onFinal, onInterim, recording]);

  const finish = useCallback(() => {
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      fail("语音识别连接已断开");
      return;
    }
    socket.send(JSON.stringify({ action: "finish" }));
    doneTimerRef.current = window.setTimeout(() => {
      fail("语音识别超时，请重试");
    }, DONE_TIMEOUT_MS);
  }, [fail]);

  const cancel = useCallback(() => {
    cleanup();
    setRecording(false);
    setInterimText("");
  }, [cleanup]);

  return { recording, interimText, error, start, finish, cancel };
}
