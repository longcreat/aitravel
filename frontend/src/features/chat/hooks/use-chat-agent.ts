import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteSession,
  getSession,
  listSessions,
  renameSession,
  streamChat,
} from "@/features/chat/api/chat.api";
import type {
  ChatDebugInfo,
  ChatFinalPayload,
  ChatMessageItem,
  SerializedLangChainMessage,
  SessionSummary,
  ToolTrace,
} from "@/features/chat/model/chat.types";

function createThreadId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createMessageId() {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createGreetingMessage(): ChatMessageItem {
  return {
    id: createMessageId(),
    role: "assistant",
    text: "你好，我是你的 AI 旅行 Agent。告诉我目的地、时间或想了解的问题，我会结合工具给你建议。",
  };
}

const fallbackDebugInfo: ChatDebugInfo = {
  tool_traces: [],
  mcp_connected_servers: [],
  mcp_errors: [],
};

function contentToText(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && "type" in item && "text" in item) {
          const typed = item as { type?: unknown; text?: unknown };
          if (typed.type === "text" && typeof typed.text === "string") {
            return typed.text;
          }
        }
        try {
          return JSON.stringify(item);
        } catch {
          return String(item);
        }
      })
      .join("");
  }
  if (content == null) {
    return "";
  }
  return String(content);
}

function isSerializedLangChainMessage(value: unknown): value is SerializedLangChainMessage {
  return Boolean(
    value &&
      typeof value === "object" &&
      "type" in value &&
      "data" in value &&
      typeof (value as { type?: unknown }).type === "string" &&
      (value as { data?: unknown }).data &&
      typeof (value as { data?: unknown }).data === "object",
  );
}

function collectSerializedMessages(payload: unknown): SerializedLangChainMessage[] {
  if (isSerializedLangChainMessage(payload)) {
    return [payload];
  }

  if (Array.isArray(payload)) {
    return payload.flatMap((item) => collectSerializedMessages(item));
  }

  if (payload && typeof payload === "object") {
    return Object.values(payload).flatMap((item) => collectSerializedMessages(item));
  }

  return [];
}

function extractMessageChunk(payload: unknown): SerializedLangChainMessage | null {
  const messages = collectSerializedMessages(payload);
  return messages.find((message) => message.type === "AIMessageChunk") ?? null;
}

function extractLatestAssistantText(payload: unknown): string {
  const messages = collectSerializedMessages(payload);
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message && (message.type === "human" || message.type === "HumanMessage")) {
      break;
    }
    if (message && (message.type === "ai" || message.type === "AIMessage")) {
      const text = contentToText(message.data.content);
      if (text) return text;
    }
  }
  return "";
}

function traceCallKey(toolName: string, payload: unknown): string {
  try {
    return `${toolName}:${JSON.stringify(payload)}`;
  } catch {
    return `${toolName}:${String(payload)}`;
  }
}

function collectToolTraces(
  payload: unknown,
  seenCalled: Set<string>,
  seenReturned: Set<string>,
): ToolTrace[] {
  const messages = collectSerializedMessages(payload);
  const traces: ToolTrace[] = [];

  for (const message of messages) {
    if (message.type === "ai" || message.type === "AIMessage") {
      for (const call of message.data.tool_calls ?? []) {
        const toolName = String(call?.name ?? "unknown");
        const args = call?.args ?? {};
        const callId = String(call?.id ?? traceCallKey(toolName, args));
        if (seenCalled.has(callId)) {
          continue;
        }
        seenCalled.add(callId);
        traces.push({
          phase: "called",
          tool_name: toolName,
          payload: args,
        });
      }
      continue;
    }

    if (message.type !== "tool") {
      continue;
    }

    const toolName = String(message.data.name ?? "unknown");
    const payloadText = contentToText(message.data.content);
    const returnedKey = String(message.data.tool_call_id ?? `${toolName}:${payloadText}`);
    if (seenReturned.has(returnedKey)) {
      continue;
    }
    seenReturned.add(returnedKey);
    traces.push({
      phase: "returned",
      tool_name: toolName,
      payload: payloadText,
    });
  }

  return traces;
}

function buildFinalPayloadFromValues(
  payload: unknown,
  streamedText: string,
  streamedToolTraces: ToolTrace[],
): ChatFinalPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const typedPayload = payload as { messages?: unknown };
  const assistantMessage = extractLatestAssistantText(typedPayload.messages) || streamedText;

  if (!assistantMessage) {
    return null;
  }

  return {
    assistant_message: assistantMessage,
    debug: {
      ...fallbackDebugInfo,
      tool_traces: [...streamedToolTraces],
    },
  };
}

export function useChatAgent() {
  const [threadId, setThreadId] = useState<string>(() => createThreadId());
  const [messages, setMessages] = useState<ChatMessageItem[]>([createGreetingMessage()]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSubmittedMessageRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const canSend = useMemo(() => !loading, [loading]);

  const refreshSessions = useCallback(async () => {
    try {
      const next = await listSessions();
      setSessions(next);
    } catch {
      // 会话列表失败不阻断聊天主链路。
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  const startNewSession = useCallback(() => {
    setThreadId(createThreadId());
    setMessages([createGreetingMessage()]);
    setError(null);
  }, []);

  const openSession = useCallback(async (targetThreadId: string) => {
    setLoading(true);
    setError(null);
    try {
      const detail = await getSession(targetThreadId);
      setThreadId(targetThreadId);

      const restored = detail.messages.map((message) => ({
        id: `persisted-${message.id}`,
        role: message.role,
        text: message.text,
        debug: message.debug ?? undefined,
      }));

      setMessages(restored.length ? restored : [createGreetingMessage()]);
    } catch (openError) {
      const message = openError instanceof Error ? openError.message : "加载会话失败";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  const renameSessionTitle = useCallback(
    async (targetThreadId: string, title: string) => {
      await renameSession(targetThreadId, title);
      await refreshSessions();
    },
    [refreshSessions],
  );

  const removeSession = useCallback(
    async (targetThreadId: string) => {
      await deleteSession(targetThreadId);

      if (targetThreadId === threadId) {
        startNewSession();
      }
      await refreshSessions();
    },
    [refreshSessions, startNewSession, threadId],
  );

  async function sendMessage(text: string) {
    const normalized = text.trim();
    if (!normalized || !canSend) {
      return;
    }

    setError(null);

    const userMessageId = createMessageId();
    const assistantMessageId = createMessageId();
    const streamedToolTraces: ToolTrace[] = [];
    const seenCalled = new Set<string>();
    const seenReturned = new Set<string>();
    let streamedText = "";
    let hasValuesResult = false;

    setMessages((prev) => [
      ...prev,
      { id: userMessageId, role: "user", text: normalized },
      { id: assistantMessageId, role: "assistant", text: "", status: "streaming" },
    ]);
    setLoading(true);
    lastSubmittedMessageRef.current = normalized;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const patchAssistantMessage = (updater: (draft: ChatMessageItem) => ChatMessageItem) => {
      setMessages((prev) => prev.map((item) => (item.id === assistantMessageId ? updater(item) : item)));
    };

    try {
      await streamChat(
        {
          thread_id: threadId,
          user_message: normalized,
          locale: "zh-CN",
          session_meta: {},
        },
        {
          signal: abortController.signal,
          onEvent: (event) => {
            if (event.event === "messages") {
              const chunk = extractMessageChunk(event.data.data);
              if (!chunk) {
                return;
              }

              streamedText += contentToText(chunk.data.content);
              patchAssistantMessage((draft) => ({
                ...draft,
                text: streamedText,
                status: "streaming",
              }));
              return;
            }

            if (event.event === "updates") {
              const newTraces = collectToolTraces(event.data.data, seenCalled, seenReturned);
              if (!newTraces.length) {
                return;
              }

              streamedToolTraces.push(...newTraces);
              patchAssistantMessage((draft) => ({
                ...draft,
                debug: {
                  ...(draft.debug ?? fallbackDebugInfo),
                  tool_traces: [...streamedToolTraces],
                },
                status: "streaming",
              }));
              return;
            }

            if (event.event === "values") {
              const finalPayload = buildFinalPayloadFromValues(event.data.data, streamedText, streamedToolTraces);
              if (!finalPayload) {
                return;
              }

              hasValuesResult = true;
              patchAssistantMessage((draft) => ({
                ...draft,
                text: finalPayload.assistant_message || streamedText || draft.text,
                status: undefined,
                debug: finalPayload.debug,
              }));
              return;
            }

            if (event.event === "error") {
              setError(event.data.message);
              patchAssistantMessage((draft) => ({
                ...draft,
                text:
                  streamedText ||
                  draft.text ||
                  "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。",
                status: undefined,
              }));
            }
          },
        },
      );

      if (!hasValuesResult) {
        patchAssistantMessage((draft) => ({
          ...draft,
          text: streamedText || draft.text || "当前未拿到完整响应，请重试。",
          status: draft.status === "stopped" ? "stopped" : undefined,
          debug: draft.debug ?? { ...fallbackDebugInfo, tool_traces: [...streamedToolTraces] },
        }));
      }
    } catch (invokeError) {
      if (
        (invokeError instanceof DOMException && invokeError.name === "AbortError") ||
        (invokeError instanceof Error && invokeError.name === "AbortError")
      ) {
        patchAssistantMessage((draft) => ({
          ...draft,
          text: draft.text || "已停止生成",
          status: "stopped",
          debug: draft.debug ?? { ...fallbackDebugInfo, tool_traces: [...streamedToolTraces] },
        }));
        return;
      }

      const message = invokeError instanceof Error ? invokeError.message : "请求失败";
      setError(message);
      patchAssistantMessage((draft) => ({
        ...draft,
        text:
          streamedText ||
          draft.text ||
          "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。",
        status: undefined,
        debug: draft.debug ?? { ...fallbackDebugInfo, tool_traces: [...streamedToolTraces] },
      }));
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      setLoading(false);
      await refreshSessions();
    }
  }

  const stopGenerating = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const retryLastSubmittedMessage = useCallback(async () => {
    const lastSubmittedMessage = lastSubmittedMessageRef.current;
    if (!lastSubmittedMessage || loading) {
      return;
    }
    await sendMessage(lastSubmittedMessage);
  }, [loading]);

  return {
    threadId,
    messages,
    sessions,
    loading,
    error,
    canSend,
    sendMessage,
    openSession,
    renameSessionTitle,
    removeSession,
    startNewSession,
    stopGenerating,
    retryLastSubmittedMessage,
    refreshSessions,
  };
}
