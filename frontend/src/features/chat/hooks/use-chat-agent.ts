import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteSession,
  getSession,
  listSessions,
  renameSession,
  streamChat,
} from "@/features/chat/api/chat.api";
import type {
  ChatChunkFrame,
  ChatDebugInfo,
  ChatMessageItem,
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
    text: "你好，我是你的 AI 旅行 Agent。告诉我目的地、天数和预算，我会帮你生成结构化行程。",
  };
}

const fallbackDebugInfo: ChatDebugInfo = {
  tool_traces: [],
  mcp_connected_servers: [],
  mcp_errors: [],
};

function chunkContentToText(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    const chunks = content.map((item) => {
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
    });
    return chunks.join("");
  }
  if (content == null) {
    return "";
  }
  return String(content);
}

export function useChatAgent() {
  const [threadId, setThreadId] = useState<string>(() => createThreadId());
  const [messages, setMessages] = useState<ChatMessageItem[]>([createGreetingMessage()]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        itinerary: message.itinerary,
        followups: message.followups,
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
    const streamedChunkFrames: ChatChunkFrame[] = [];
    let streamedText = "";
    let hasFinalEvent = false;

    setMessages((prev) => [
      ...prev,
      { id: userMessageId, role: "user", text: normalized },
      { id: assistantMessageId, role: "assistant", text: "" },
    ]);
    setLoading(true);

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
          onEvent: (event) => {
            if (event.event === "token") {
              streamedChunkFrames.push(event.data);
              streamedText += chunkContentToText(event.data.chunk.content);
              patchAssistantMessage((draft) => ({
                ...draft,
                text: streamedText,
                chunk_frames: [...streamedChunkFrames],
              }));
              return;
            }

            if (event.event === "tool_called" || event.event === "tool_returned") {
              streamedToolTraces.push({
                phase: event.event === "tool_called" ? "called" : "returned",
                tool_name: event.data.tool_name,
                payload: event.data.payload,
              });

              patchAssistantMessage((draft) => ({
                ...draft,
                debug: {
                  ...(draft.debug ?? fallbackDebugInfo),
                  tool_traces: [...streamedToolTraces],
                },
              }));
              return;
            }

            if (event.event === "final") {
              hasFinalEvent = true;
              const mergedToolTraces =
                event.data.debug?.tool_traces?.length > 0 ? event.data.debug.tool_traces : [...streamedToolTraces];
              const finalText = event.data.assistant_message || streamedText;

              patchAssistantMessage((draft) => ({
                ...draft,
                text: finalText,
                chunk_frames: draft.chunk_frames ?? [...streamedChunkFrames],
                itinerary: event.data.itinerary,
                followups: event.data.followups,
                debug: {
                  ...(event.data.debug ?? fallbackDebugInfo),
                  tool_traces: mergedToolTraces,
                },
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
              }));
            }
          },
        },
      );

      if (!hasFinalEvent) {
        patchAssistantMessage((draft) => ({
          ...draft,
          text: streamedText || draft.text || "当前未拿到完整响应，请重试。",
          chunk_frames: draft.chunk_frames ?? [...streamedChunkFrames],
          debug: draft.debug ?? { ...fallbackDebugInfo, tool_traces: [...streamedToolTraces] },
        }));
      }
    } catch (invokeError) {
      const message = invokeError instanceof Error ? invokeError.message : "请求失败";
      setError(message);
      patchAssistantMessage((draft) => ({
        ...draft,
        text:
          streamedText ||
          draft.text ||
          "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。",
        chunk_frames: draft.chunk_frames ?? [...streamedChunkFrames],
        debug: draft.debug ?? { ...fallbackDebugInfo, tool_traces: [...streamedToolTraces] },
      }));
    } finally {
      setLoading(false);
      await refreshSessions();
    }
  }

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
    refreshSessions,
  };
}
