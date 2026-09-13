import { useCallback, useEffect, useRef, useState } from "react";

import type { SendIntentResult } from "@/features/chat/model/chat.types";

interface UseVoiceUtterancesOptions {
  /** 切换会话时清空未完成的语音消息，避免发进错误的线程 */
  threadId: string;
  /** agent 是否正在流式回复；忙时语音消息排队等待 */
  loading: boolean;
  ready: boolean;
  sendMessage: (text: string) => Promise<SendIntentResult>;
  /** 语音识别失败（无文本）时的提示出口 */
  onFailed?: (message: string | null) => void;
}

export interface VoiceUtterances {
  /** 转写中 / 排队中的话语 id，聊天区按序渲染等待气泡 */
  pendingIds: string[];
  started: (id: string) => void;
  resolved: (id: string, text: string) => void;
  failed: (id: string, message: string | null) => void;
}

export function useVoiceUtterances(options: UseVoiceUtterancesOptions): VoiceUtterances {
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  // 入队/出队都推进版本号：队列本身是 ref，不触发渲染，靠版本驱动 drain effect
  const [queueVersion, setQueueVersion] = useState(0);
  const pendingIdsRef = useRef<string[]>([]);
  const queueRef = useRef<Array<{ id: string; text: string }>>([]);
  const sendingRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const setIds = useCallback((next: string[]) => {
    pendingIdsRef.current = next;
    setPendingIds(next);
  }, []);

  const started = useCallback(
    (id: string) => {
      setIds([...pendingIdsRef.current, id]);
    },
    [setIds],
  );

  const resolved = useCallback(
    (id: string, text: string) => {
      // 气泡先不撤：等消息真正开始发送时再移除，与真实用户消息无缝衔接
      queueRef.current.push({ id, text });
      setQueueVersion((version) => version + 1);
    },
    [],
  );

  const failed = useCallback(
    (id: string, message: string | null) => {
      setIds(pendingIdsRef.current.filter((item) => item !== id));
      optionsRef.current.onFailed?.(message);
    },
    [setIds],
  );

  // 串行发送：上一条流式回复结束后自动发下一条，保证会话内消息顺序
  useEffect(() => {
    if (options.loading || !options.ready || sendingRef.current) {
      return;
    }
    const next = queueRef.current.shift();
    if (!next) {
      return;
    }
    sendingRef.current = true;
    void (async () => {
      try {
        const result = await optionsRef.current.sendMessage(next.text);
        if (result.status === "blocked") {
          // 忙时放回队头，等待下一轮 drain
          queueRef.current.unshift(next);
          return;
        }
        // accepted：真实消息即将由 turn.start 渲染；auth_required：登录后由续发流程接管
        setIds(pendingIdsRef.current.filter((item) => item !== next.id));
      } finally {
        sendingRef.current = false;
        setQueueVersion((version) => version + 1);
      }
    })();
  }, [options.loading, options.ready, queueVersion, setIds]);

  // 切换会话：丢弃未发送的语音消息并清空气泡
  useEffect(() => {
    queueRef.current = [];
    setIds([]);
  }, [options.threadId, setIds]);

  return { pendingIds, started, resolved, failed };
}
