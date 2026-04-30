import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/features/auth/model/auth.context";
import { consumePendingAuthMessage } from "@/features/auth/model/auth.storage";
import {
  deleteSession,
  getSession,
  listChatModelProfiles,
  listSessions,
  regenerateAssistantMessage,
  renameSession,
  streamChat,
  switchAssistantVersion,
  updateAssistantFeedback,
  updateSessionModelProfile,
} from "@/features/chat/api/chat.api";
import type {
  AssistantVersionFeedback,
  ChatMessageItem,
  ChatMessagePart,
  ChatModelProfile,
  ChatStreamEvent,
  PersistedChatMessage,
  SendIntentResult,
  SessionSummary,
} from "@/features/chat/model/chat.types";

function createThreadId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function toChatMessageItem(message: PersistedChatMessage): ChatMessageItem {
  return {
    id: `persisted-${message.id}`,
    role: message.role,
    text: message.text,
    parts: message.parts ?? [],
    status: message.status,
    meta: message.meta ?? undefined,
    current_version_id: message.current_version_id ?? undefined,
    versions: message.versions ?? [],
    can_regenerate: message.can_regenerate ?? false,
  };
}

function mergeTextDelta(parts: ChatMessagePart[], event: Extract<ChatStreamEvent, { event: "part.delta" }>["data"]) {
  const next = [...parts];
  const index = next.findIndex((part) => part.id === event.part_id);
  if (index >= 0) {
    const part = next[index];
    if (part.type === event.part_type) {
      const toolAfterTextPart =
        event.part_type === "text" && next.slice(index + 1).some((candidate) => candidate.type === "tool");
      if (toolAfterTextPart) {
        let lastToolIndex = -1;
        for (let candidateIndex = next.length - 1; candidateIndex >= 0; candidateIndex -= 1) {
          if (next[candidateIndex]?.type === "tool") {
            lastToolIndex = candidateIndex;
            break;
          }
        }
        const continuationId = `${event.part_id}-after-tool-${lastToolIndex}`;
        const continuationIndex = next.findIndex((candidate) => candidate.id === continuationId);
        if (continuationIndex >= 0) {
          const continuationPart = next[continuationIndex];
          if (continuationPart.type === "text") {
            next[continuationIndex] = {
              ...continuationPart,
              text: continuationPart.text + event.text_delta,
              status: event.status,
            };
            return next;
          }
        }

        next.push({
          id: continuationId,
          type: "text",
          text: event.text_delta,
          status: event.status,
        });
        return next;
      }

      next[index] = {
        ...part,
        text: part.text + event.text_delta,
        status: event.status,
      } as ChatMessagePart;
      return next;
    }
  }

  next.push({
    id: event.part_id,
    type: event.part_type,
    text: event.text_delta,
    status: event.status,
  } as ChatMessagePart);
  return next;
}

function upsertToolPart(parts: ChatMessagePart[], toolPart: Extract<ChatMessagePart, { type: "tool" }>) {
  const next = [...parts];
  const index = next.findIndex((part) => part.id === toolPart.id);
  if (index >= 0) {
    next[index] = toolPart;
    return next;
  }
  next.push(toolPart);
  return next;
}

function visibleTextFromParts(parts: ChatMessagePart[]) {
  return parts
    .filter((part): part is Extract<ChatMessagePart, { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("");
}

export function useChatAgent(initialThreadId?: string) {
  const { isAuthenticated, openAuthModal, ready } = useAuth();
  const [threadId, setThreadId] = useState<string>(() => initialThreadId ?? createThreadId());
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsReady, setSessionsReady] = useState(false);
  const [modelProfiles, setModelProfiles] = useState<ChatModelProfile[]>([]);
  const [defaultModelProfileKey, setDefaultModelProfileKey] = useState("");
  const [selectedModelProfileKey, setSelectedModelProfileKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeThreadIdRef = useRef(threadId);
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestInFlightRef = useRef(false);
  const lastSubmittedMessageRef = useRef<string | null>(null);
  const previousDefaultModelProfileKeyRef = useRef("");

  useEffect(() => {
    activeThreadIdRef.current = threadId;
  }, [threadId]);

  const currentThreadIsPersisted = useMemo(
    () =>
      sessions.some((session) => session.thread_id === threadId) ||
      messages.some((message) => message.id.startsWith("persisted-")),
    [messages, sessions, threadId],
  );
  const selectedModelProfile = useMemo(
    () => modelProfiles.find((profile) => profile.key === selectedModelProfileKey) ?? null,
    [modelProfiles, selectedModelProfileKey],
  );
  const canStartRequest = useMemo(() => ready && !loading, [loading, ready]);

  const refreshSessions = useCallback(async () => {
    if (!isAuthenticated) {
      setSessions([]);
      setSessionsReady(true);
      return;
    }
    try {
      setSessions(await listSessions());
    } catch {
      // 会话列表失败不阻断聊天主链路。
    } finally {
      setSessionsReady(true);
    }
  }, [isAuthenticated]);

  const hydrateThreadMessages = useCallback(async (targetThreadId: string) => {
    const detail = await getSession(targetThreadId);
    if (activeThreadIdRef.current === targetThreadId) {
      const nextMessages = detail.messages.map(toChatMessageItem);
      setMessages(nextMessages);
      setSelectedModelProfileKey(detail.model_profile_key);
    }
    return detail;
  }, []);

  const refreshCurrentThread = useCallback(async () => {
    if (!isAuthenticated || !currentThreadIsPersisted) {
      return;
    }
    await hydrateThreadMessages(threadId);
  }, [currentThreadIsPersisted, hydrateThreadMessages, isAuthenticated, threadId]);

  const refreshModelProfiles = useCallback(async () => {
    try {
      const response = await listChatModelProfiles();
      setModelProfiles(response.profiles);
      setDefaultModelProfileKey(response.default_profile_key);
      setSelectedModelProfileKey((current) => {
        const previousDefault = previousDefaultModelProfileKeyRef.current;
        previousDefaultModelProfileKeyRef.current = response.default_profile_key;
        if (!current || current === previousDefault) return response.default_profile_key;
        return response.profiles.some((profile) => profile.key === current) ? current : response.default_profile_key;
      });
    } catch {
      setModelProfiles([]);
    }
  }, []);

  useEffect(() => {
    void refreshModelProfiles();
  }, [refreshModelProfiles]);

  useEffect(() => {
    if (ready) {
      void refreshSessions();
    }
  }, [ready, refreshSessions]);

  const startNewSession = useCallback(() => {
    const nextThreadId = createThreadId();
    activeThreadIdRef.current = nextThreadId;
    setThreadId(nextThreadId);
    setMessages([]);
    setError(null);
    setSelectedModelProfileKey(defaultModelProfileKey);
    return nextThreadId;
  }, [defaultModelProfileKey]);

  const openSession = useCallback(
    async (targetThreadId: string) => {
      setLoading(true);
      setError(null);
      try {
        activeThreadIdRef.current = targetThreadId;
        setThreadId(targetThreadId);
        await hydrateThreadMessages(targetThreadId);
      } catch (openError) {
        setError(openError instanceof Error ? openError.message : "加载会话失败");
      } finally {
        setLoading(false);
      }
    },
    [hydrateThreadMessages],
  );

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
      if (targetThreadId === threadId) startNewSession();
      await refreshSessions();
    },
    [refreshSessions, startNewSession, threadId],
  );

  const updateCurrentModelProfile = useCallback(
    async (nextModelProfileKey: string) => {
      setSelectedModelProfileKey(nextModelProfileKey);
      if (!isAuthenticated || !currentThreadIsPersisted) return;

      const previousModelProfileKey = selectedModelProfileKey;
      try {
        await updateSessionModelProfile(threadId, { model_profile_key: nextModelProfileKey });
      } catch (updateError) {
        setSelectedModelProfileKey(previousModelProfileKey);
        setError(updateError instanceof Error ? updateError.message : "切换模型失败");
      }
    },
    [currentThreadIsPersisted, isAuthenticated, selectedModelProfileKey, threadId],
  );

  const patchMessage = useCallback((messageId: string, updater: (message: ChatMessageItem) => ChatMessageItem) => {
    setMessages((prev) => prev.map((item) => (item.id === `persisted-${messageId}` ? updater(item) : item)));
  }, []);

  function applyStreamEvent(
    event: ChatStreamEvent,
    context: {
      targetThreadId: string;
      activeAssistantMessageIdRef: { current: string | null };
      activeUserMessageIdRef: { current: string | null };
      modelProfileKey: string | null;
      fallbackAssistantMessage?: ChatMessageItem | null;
    },
  ) {
    if (event.event === "turn.start") {
      const nextAssistantItem = toChatMessageItem(event.data.assistant_message);
      const assistantItem =
        context.fallbackAssistantMessage?.id === nextAssistantItem.id
          ? {
              ...context.fallbackAssistantMessage,
              current_version_id: nextAssistantItem.current_version_id,
              versions: nextAssistantItem.versions,
              status: "streaming" as const,
              can_regenerate: false,
            }
          : nextAssistantItem;
      context.activeAssistantMessageIdRef.current = event.data.assistant_message.id;
      context.activeUserMessageIdRef.current = event.data.user_message?.id ?? null;
      setMessages((prev) => {
        const withoutAssistant = prev.filter((item) => item.id !== assistantItem.id);
        const userItem = event.data.user_message ? toChatMessageItem(event.data.user_message) : null;
        if (!userItem) return [...withoutAssistant, assistantItem];
        const withoutUser = withoutAssistant.filter((item) => item.id !== userItem.id);
        return [...withoutUser, userItem, assistantItem];
      });
      return;
    }

    if (event.event === "part.delta") {
      patchMessage(event.data.message_id, (message) => {
        const parts = mergeTextDelta(message.parts ?? [], event.data);
        return {
          ...message,
          parts,
          text: visibleTextFromParts(parts),
          status: "streaming",
        };
      });
      return;
    }

    if (event.event === "tool.start" || event.event === "tool.done") {
      patchMessage(event.data.message_id, (message) => ({
        ...message,
        parts: upsertToolPart(message.parts ?? [], event.data.part),
        status: "streaming",
      }));
      return;
    }

    if (event.event === "message.completed") {
      const completedItem = toChatMessageItem(event.data.message);
      setMessages((prev) =>
        prev.map((item) => (item.id === completedItem.id ? completedItem : item)),
      );
      return;
    }

    if (event.event === "error") {
      const fallbackAssistantMessage = context.fallbackAssistantMessage;
      if (fallbackAssistantMessage) {
        setMessages((prev) => prev.map((item) => (item.id === fallbackAssistantMessage.id ? fallbackAssistantMessage : item)));
        setError(event.data.message);
        return;
      }
      const assistantMessageId = context.activeAssistantMessageIdRef.current;
      if (assistantMessageId) {
        patchMessage(assistantMessageId, (message) => ({
          ...message,
          status: "failed",
          text: message.text || event.data.message,
          parts: (message.parts ?? []).length
            ? message.parts
            : [{ id: "text-1", type: "text", text: event.data.message, status: "failed" }],
        }));
      }
      setError(event.data.message);
    }
  }

  const prepareSendIntent = useCallback(
    (text: string): SendIntentResult => {
      const normalized = text.trim();
      if (!normalized) return { status: "blocked", reason: "empty" };
      if (loading || requestInFlightRef.current) return { status: "blocked", reason: "loading" };
      if (!ready) return { status: "blocked", reason: "not_ready" };
      if (!isAuthenticated) return { status: "auth_required", message: normalized };
      return { status: "accepted", message: normalized };
    },
    [isAuthenticated, loading, ready],
  );

  async function executeSend(
    normalized: string,
    modelProfileKeyOverride?: string | null,
  ) {
    requestInFlightRef.current = true;
    setLoading(true);
    setError(null);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const targetThreadId = threadId;
    const effectiveModelProfileKey = (modelProfileKeyOverride ?? selectedModelProfileKey) || null;
    const activeAssistantMessageIdRef = { current: null as string | null };
    const activeUserMessageIdRef = { current: null as string | null };

    try {
      const onEvent = (event: ChatStreamEvent) =>
        applyStreamEvent(event, {
          targetThreadId,
          activeAssistantMessageIdRef,
          activeUserMessageIdRef,
          modelProfileKey: effectiveModelProfileKey,
        });

      lastSubmittedMessageRef.current = normalized;
      await streamChat(
        {
          thread_id: targetThreadId,
          user_message: normalized,
          locale: "zh-CN",
          model_profile_key: effectiveModelProfileKey,
          session_meta: {},
        },
        { signal: abortController.signal, onEvent },
      );
      await refreshSessions();
    } catch (invokeError) {
      if (
        (invokeError instanceof DOMException && invokeError.name === "AbortError") ||
        (invokeError instanceof Error && invokeError.name === "AbortError")
      ) {
        if (activeAssistantMessageIdRef.current) {
          patchMessage(activeAssistantMessageIdRef.current, (message) => ({
            ...message,
            status: "stopped",
            parts: (message.parts ?? []).map((part) =>
              part.type === "text" || part.type === "reasoning" ? { ...part, status: "stopped" } : part,
            ),
          }));
        }
        return;
      }
      setError(invokeError instanceof Error ? invokeError.message : "请求失败，请稍后重试。");
    } finally {
      requestInFlightRef.current = false;
      if (abortControllerRef.current === abortController) abortControllerRef.current = null;
      setLoading(false);
    }
  }

  async function sendMessage(text: string, options?: { modelProfileKey?: string | null }): Promise<SendIntentResult> {
    const intent = prepareSendIntent(text);
    if (intent.status === "auth_required") {
      openAuthModal({
        redirectTo: "/chat",
        initialMode: "login",
        pendingMessage: {
          message: intent.message,
          model_profile_key: (options?.modelProfileKey ?? selectedModelProfileKey) || null,
        },
      });
      return intent;
    }
    if (intent.status !== "accepted") return intent;
    void executeSend(intent.message, options?.modelProfileKey);
    return intent;
  }

  async function regenerateLatestAssistantMessage(messageId: string) {
    if (loading || !isAuthenticated) return;
    setLoading(true);
    setError(null);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const activeAssistantMessageIdRef = { current: messageId };
    const fallbackAssistantMessage = messages.find((item) => item.id === `persisted-${messageId}`) ?? null;
    let regenerateContentStarted = false;
    try {
      await regenerateAssistantMessage(threadId, messageId, {
        signal: abortController.signal,
        onEvent: (event) => {
          if (
            fallbackAssistantMessage &&
            !regenerateContentStarted &&
            (event.event === "part.delta" || event.event === "tool.start" || event.event === "tool.done")
          ) {
            regenerateContentStarted = true;
            setMessages((prev) =>
              prev.map((item) =>
                item.id === fallbackAssistantMessage.id
                  ? { ...item, text: "", parts: [], status: "streaming" }
                  : item,
              ),
            );
          }
          applyStreamEvent(event, {
            targetThreadId: threadId,
            activeAssistantMessageIdRef,
            activeUserMessageIdRef: { current: null },
            modelProfileKey: selectedModelProfileKey || null,
            fallbackAssistantMessage,
          });
        },
      });
      await refreshSessions();
    } catch (regenerateError) {
      if (
        (regenerateError instanceof DOMException && regenerateError.name === "AbortError") ||
        (regenerateError instanceof Error && regenerateError.name === "AbortError")
      ) {
        patchMessage(messageId, (message) => ({ ...message, status: "stopped" }));
        return;
      }
      if (fallbackAssistantMessage) {
        setMessages((prev) => prev.map((item) => (item.id === fallbackAssistantMessage.id ? fallbackAssistantMessage : item)));
      }
      setError(regenerateError instanceof Error ? regenerateError.message : "重新生成失败");
    } finally {
      if (abortControllerRef.current === abortController) abortControllerRef.current = null;
      setLoading(false);
    }
  }

  async function selectAssistantVersion(messageId: string, versionId: string) {
    const updated = await switchAssistantVersion(threadId, messageId, { version_id: versionId });
    setMessages((prev) => prev.map((item) => (item.id === `persisted-${messageId}` ? toChatMessageItem(updated) : item)));
    await refreshSessions();
  }

  async function setAssistantFeedback(messageId: string, versionId: string, feedback: AssistantVersionFeedback) {
    const updated = await updateAssistantFeedback(threadId, messageId, versionId, { feedback });
    setMessages((prev) => prev.map((item) => (item.id === `persisted-${messageId}` ? toChatMessageItem(updated) : item)));
  }

  const stopGenerating = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const retryLastSubmittedMessage = useCallback(async () => {
    const lastSubmittedMessage = lastSubmittedMessageRef.current;
    if (!lastSubmittedMessage || loading) return;
    await sendMessage(lastSubmittedMessage);
  }, [loading]);

  useEffect(() => {
    if (!ready || !isAuthenticated || loading) return;
    const pendingIntent = consumePendingAuthMessage();
    if (!pendingIntent) return;
    if (pendingIntent.model_profile_key) setSelectedModelProfileKey(pendingIntent.model_profile_key);
    void sendMessage(pendingIntent.message, {
      modelProfileKey: pendingIntent.model_profile_key ?? null,
    });
  }, [isAuthenticated, loading, ready]);

  return {
    threadId,
    messages,
    sessions,
    sessionsReady,
    modelProfiles,
    defaultModelProfileKey,
    selectedModelProfileKey,
    selectedModelProfile,
    loading,
    error,
    isAuthenticated,
    canStartRequest,
    sendMessage,
    openSession,
    renameSessionTitle,
    removeSession,
    startNewSession,
    stopGenerating,
    regenerateLatestAssistantMessage,
    selectAssistantVersion,
    setAssistantFeedback,
    updateCurrentModelProfile,
    retryLastSubmittedMessage,
    refreshCurrentThread,
  };
}
