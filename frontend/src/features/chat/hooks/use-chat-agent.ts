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
  streamChatResume,
  switchAssistantVersion,
  updateSessionModelProfile,
  updateAssistantFeedback,
} from "@/features/chat/api/chat.api";
import type {
  AssistantVersionFeedback,
  ChatInterruptPayload,
  ChatModelProfile,
  ChatMetaInfo,
  ChatFinalPayload,
  ChatRenderSegment,
  ChatMessageItem,
  ChatStreamEvent,
  SendIntentResult,
  SerializedLangChainMessage,
  SessionDetail,
  SessionSummary,
  StepDetailItem,
  StepGroup,
  ToolTrace,
} from "@/features/chat/model/chat.types";

interface PendingInterruptState extends ChatInterruptPayload {
  assistant_message_id: string;
  thread_id: string;
  model_profile_key: string | null;
}

function createThreadId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createMessageId() {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const fallbackMetaInfo: ChatMetaInfo = {
  tool_traces: [],
  step_groups: [],
  render_segments: [],
  reasoning_text: null,
  reasoning_state: null,
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
          if (typed.type === "reasoning" || typed.type === "reasoning_content") {
            return "";
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
  if (typeof content === "object") {
    try {
      return JSON.stringify(content);
    } catch {
      return String(content);
    }
  }
  return String(content);
}

function getToolReturnPayload(message: SerializedLangChainMessage["data"]): unknown {
  if (message.artifact !== null && message.artifact !== undefined) {
    return message.artifact;
  }
  return contentToText(message.content);
}

function contentToReasoningText(content: unknown): string {
  if (!Array.isArray(content)) {
    return "";
  }

  return content
    .flatMap((item) => {
      if (!item || typeof item !== "object") {
        return [];
      }

      const typed = item as {
        type?: unknown;
        reasoning?: unknown;
        reasoning_content?: unknown;
        summary?: unknown;
        text?: unknown;
      };

      if (typed.type !== "reasoning" && typed.type !== "reasoning_content") {
        return [];
      }

      const chunks: string[] = [];
      if (typeof typed.reasoning === "string" && typed.reasoning) {
        chunks.push(typed.reasoning);
      }
      if (typeof typed.reasoning_content === "string" && typed.reasoning_content) {
        chunks.push(typed.reasoning_content);
      }
      if (typed.type === "reasoning_content" && typeof typed.text === "string" && typed.text) {
        chunks.push(typed.text);
      }
      if (Array.isArray(typed.summary)) {
        for (const summaryItem of typed.summary) {
          if (
            summaryItem &&
            typeof summaryItem === "object" &&
            "type" in summaryItem &&
            "text" in summaryItem &&
            (summaryItem as { type?: unknown }).type === "summary_text" &&
            typeof (summaryItem as { text?: unknown }).text === "string"
          ) {
            chunks.push((summaryItem as { text: string }).text);
          }
        }
      }
      return chunks;
    })
    .join("");
}

function extractReasoningTextFromSerializedMessage(message: SerializedLangChainMessage): string {
  const reasoningFromAdditionalKwargs = message.data.additional_kwargs?.reasoning_content;
  if (typeof reasoningFromAdditionalKwargs === "string" && reasoningFromAdditionalKwargs.trim()) {
    return reasoningFromAdditionalKwargs;
  }
  return contentToReasoningText(message.data.content);
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
      if ((message.data.tool_calls?.length ?? 0) > 0) {
        continue;
      }
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
        // request_user_clarification 是 human-in-the-loop 的内部机制，interrupt UI 已处理展示，
        // Step Summary 中不显示此工具（任何阶段）。
        if (toolName === "request_user_clarification") {
          continue;
        }
        traces.push({
          phase: "called",
          tool_name: toolName,
          payload: args,
          tool_call_id: callId,
          result_status: null,
        });
      }
      continue;
    }

    if (message.type !== "tool") {
      continue;
    }

    const toolName = String(message.data.name ?? "unknown");
    // 同上：request_user_clarification 的返回结果也不在 Summary 显示。
    if (toolName === "request_user_clarification") {
      continue;
    }
    const payloadText = contentToText(message.data.content);
    const returnedPayload = getToolReturnPayload(message.data);
    const returnedKey = String(message.data.tool_call_id ?? `${toolName}:${payloadText}`);
    if (seenReturned.has(returnedKey)) {
      continue;
    }
    seenReturned.add(returnedKey);
    traces.push({
      phase: "returned",
      tool_name: toolName,
      payload: returnedPayload,
      tool_call_id: returnedKey,
      result_status: message.data.status === "error" ? "error" : "success",
    });
  }

  return traces;
}

function cloneStepGroups(stepGroups: StepGroup[]): StepGroup[] {
  return stepGroups.map((group) => ({
    id: group.id,
    items: group.items.map((item) => ({ ...item })),
  }));
}

function cloneRenderSegments(renderSegments: ChatRenderSegment[]): ChatRenderSegment[] {
  return renderSegments.map((segment) => ({ ...segment }));
}

function appendTextSegment(renderSegments: ChatRenderSegment[], chunkText: string) {
  if (!chunkText) {
    return;
  }

  const lastSegment = renderSegments[renderSegments.length - 1];
  if (lastSegment?.type === "text") {
    lastSegment.text += chunkText;
    return;
  }

  renderSegments.push({
    type: "text",
    text: chunkText,
  });
}

function getVisibleTextFromSegments(renderSegments: ChatRenderSegment[]): string {
  return renderSegments
    .filter((segment): segment is Extract<ChatRenderSegment, { type: "text" }> => segment.type === "text")
    .map((segment) => segment.text)
    .join("");
}

function summarizeToolPayload(payload: unknown, status: "running" | "success" | "error"): string {
  if (status === "running") {
    return "Running";
  }

  const text = contentToText(payload).trim();
  if (text && text.length <= 80 && !/^[\[{]/.test(text)) {
    return text;
  }

  return status === "error" ? "Returned an error" : "Completed";
}

function getOrCreateCurrentStepGroup(stepGroups: StepGroup[], renderSegments: ChatRenderSegment[]): StepGroup {
  const lastSegment = renderSegments[renderSegments.length - 1];
  if (lastSegment?.type === "step") {
    const existing = stepGroups.find((group) => group.id === lastSegment.step_group_id);
    if (existing) {
      return existing;
    }
  }

  const nextGroup: StepGroup = {
    id: `step-${stepGroups.length + 1}`,
    items: [],
  };
  stepGroups.push(nextGroup);
  renderSegments.push({
    type: "step",
    step_group_id: nextGroup.id,
  });
  return nextGroup;
}

function findExistingStepItem(stepGroups: StepGroup[], toolCallId: string) {
  for (let groupIndex = stepGroups.length - 1; groupIndex >= 0; groupIndex -= 1) {
    const item = stepGroups[groupIndex].items.find((candidate) => candidate.id === toolCallId);
    if (item) {
      return item;
    }
  }
  return null;
}

function applyToolTraceToPresentation(
  trace: ToolTrace,
  stepGroups: StepGroup[],
  renderSegments: ChatRenderSegment[],
) {
  // request_user_clarification 是 human-in-the-loop 内部机制，interrupt UI 已处理，
  // 不在 Step Summary 中显示任何阶段。
  if (trace.tool_name === "request_user_clarification") {
    return;
  }

  const normalizedCallId = trace.tool_call_id ?? `${trace.tool_name}-${stepGroups.length + 1}-${Date.now()}`;

  if (trace.phase === "called") {
    const stepGroup = getOrCreateCurrentStepGroup(stepGroups, renderSegments);
    const existing = stepGroup.items.find((item) => item.id === normalizedCallId);
    if (existing) {
      existing.tool_name = trace.tool_name;
      existing.status = "running";
      existing.summary = summarizeToolPayload(trace.payload, "running");
      return;
    }

    stepGroup.items.push({
      id: normalizedCallId,
      tool_name: trace.tool_name,
      status: "running",
      summary: summarizeToolPayload(trace.payload, "running"),
    });
    return;
  }

  const resolvedStatus: StepDetailItem["status"] = trace.result_status === "error" ? "error" : "success";
  const existingItem = findExistingStepItem(stepGroups, normalizedCallId);
  if (existingItem) {
    existingItem.tool_name = trace.tool_name;
    existingItem.status = resolvedStatus;
    existingItem.summary = summarizeToolPayload(trace.payload, resolvedStatus);
    return;
  }

  const stepGroup = getOrCreateCurrentStepGroup(stepGroups, renderSegments);
  stepGroup.items.push({
    id: normalizedCallId,
    tool_name: trace.tool_name,
    status: resolvedStatus,
    summary: summarizeToolPayload(trace.payload, resolvedStatus),
  });
}

function sliceMessagesAfterLatestHuman(messages: SerializedLangChainMessage[]): SerializedLangChainMessage[] {
  let startIndex = 0;
  for (let index = 0; index < messages.length; index += 1) {
    const messageType = messages[index]?.type;
    if (messageType === "human" || messageType === "HumanMessage") {
      startIndex = index + 1;
    }
  }
  return messages.slice(startIndex);
}

function buildPresentationFromSerializedMessages(payload: unknown) {
  const relevantMessages = sliceMessagesAfterLatestHuman(collectSerializedMessages(payload));
  const stepGroups: StepGroup[] = [];
  const renderSegments: ChatRenderSegment[] = [];
  const reasoningChunks: string[] = [];

  for (const message of relevantMessages) {
    if (message.type === "ai" || message.type === "AIMessage") {
      const reasoningText = extractReasoningTextFromSerializedMessage(message);
      if (reasoningText) {
        reasoningChunks.push(reasoningText);
      }

      const text = contentToText(message.data.content);
      if (text) {
        appendTextSegment(renderSegments, text);
      }

      const toolCalls = message.data.tool_calls ?? [];
      if (!toolCalls.length) {
        continue;
      }

      const stepGroup = getOrCreateCurrentStepGroup(stepGroups, renderSegments);
      for (const call of toolCalls) {
        const normalizedCallId = String(call?.id ?? `${call?.name ?? "tool"}-${stepGroup.items.length + 1}`);
        const existing = stepGroup.items.find((item) => item.id === normalizedCallId);
        if (existing) {
          continue;
        }
        stepGroup.items.push({
          id: normalizedCallId,
          tool_name: String(call?.name ?? "unknown"),
          status: "running",
          summary: summarizeToolPayload(call?.args ?? {}, "running"),
        });
      }
      continue;
    }

    if (message.type !== "tool") {
      continue;
    }

    // request_user_clarification 是 human-in-the-loop 内部机制，Step Summary 不显示。
    if (String(message.data.name ?? "") === "request_user_clarification") {
      continue;
    }

    const resolvedStatus: StepDetailItem["status"] = message.data.status === "error" ? "error" : "success";
    const normalizedCallId = String(message.data.tool_call_id ?? `${message.data.name ?? "tool"}-${stepGroups.length + 1}`);
    const existingItem = findExistingStepItem(stepGroups, normalizedCallId);
    if (existingItem) {
      existingItem.status = resolvedStatus;
      existingItem.summary = summarizeToolPayload(message.data.content, resolvedStatus);
      continue;
    }

    const stepGroup = getOrCreateCurrentStepGroup(stepGroups, renderSegments);
    stepGroup.items.push({
      id: normalizedCallId,
      tool_name: String(message.data.name ?? "unknown"),
      status: resolvedStatus,
      summary: summarizeToolPayload(message.data.content, resolvedStatus),
    });
  }

  return {
    assistantMessage: getVisibleTextFromSegments(renderSegments),
    reasoningText: reasoningChunks.join(""),
    stepGroups,
    renderSegments,
  };
}

function buildFinalPayloadFromValues(
  payload: unknown,
  fallbackAssistantText: string,
  streamedToolTraces: ToolTrace[],
): ChatFinalPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const typedPayload = payload as { messages?: unknown };
  const presentation = buildPresentationFromSerializedMessages(typedPayload.messages);
  const assistantMessage = presentation.assistantMessage || fallbackAssistantText;

  if (!assistantMessage && !presentation.reasoningText && !streamedToolTraces.length && !presentation.renderSegments.length) {
    return null;
  }

  return {
    assistant_message: assistantMessage || "",
    meta: {
      ...fallbackMetaInfo,
      tool_traces: [...streamedToolTraces],
      step_groups: cloneStepGroups(presentation.stepGroups),
      render_segments: cloneRenderSegments(presentation.renderSegments),
      reasoning_text: presentation.reasoningText || null,
      reasoning_state: presentation.reasoningText ? "completed" : null,
    },
  };
}

function toChatMessageItems(detailMessages: SessionDetail["messages"]): ChatMessageItem[] {
  return detailMessages.map((message) => ({
    id: `persisted-${message.id}`,
    role: message.role,
    text: message.text,
    meta: message.meta ?? undefined,
    current_version_id: message.current_version_id ?? undefined,
    versions: message.versions ?? [],
    can_regenerate: message.can_regenerate ?? false,
  }));
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
  const [pendingInterrupt, setPendingInterrupt] = useState<PendingInterruptState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSubmittedMessageRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeThreadIdRef = useRef(threadId);
  const requestInFlightRef = useRef(false);
  const previousDefaultModelProfileKeyRef = useRef("");

  useEffect(() => {
    activeThreadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    setPendingInterrupt(null);
  }, [threadId]);

  const canStartRequest = useMemo(() => ready && !loading, [loading, ready]);
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

  const refreshSessions = useCallback(async () => {
    if (!isAuthenticated) {
      setSessions([]);
      setSessionsReady(true);
      return;
    }
    try {
      const next = await listSessions();
      setSessions(next);
    } catch {
      // 会话列表失败不阻断聊天主链路。
    } finally {
      setSessionsReady(true);
    }
  }, [isAuthenticated]);

  const refreshModelProfiles = useCallback(async () => {
    try {
      const response = await listChatModelProfiles();
      setModelProfiles(response.profiles);
      setDefaultModelProfileKey(response.default_profile_key);
      setSelectedModelProfileKey((current) => {
        const previousDefault = previousDefaultModelProfileKeyRef.current;
        previousDefaultModelProfileKeyRef.current = response.default_profile_key;
        if (!current || current === previousDefault) {
          return response.default_profile_key;
        }
        if (response.profiles.some((profile) => profile.key === current)) {
          return current;
        }
        return response.default_profile_key;
      });
    } catch {
      setModelProfiles([]);
    }
  }, []);

  const hydrateThreadMessages = useCallback(async (targetThreadId: string) => {
    const detail = await getSession(targetThreadId);
    if (activeThreadIdRef.current === targetThreadId) {
      setPendingInterrupt(null);
      setMessages(toChatMessageItems(detail.messages));
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

  useEffect(() => {
    void refreshModelProfiles();
  }, [refreshModelProfiles]);

  useEffect(() => {
    if (!ready) {
      return;
    }
    void refreshSessions();
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

  const openSession = useCallback(async (targetThreadId: string) => {
    setLoading(true);
    setError(null);
    try {
      activeThreadIdRef.current = targetThreadId;
      setThreadId(targetThreadId);
      await hydrateThreadMessages(targetThreadId);
    } catch (openError) {
      const message = openError instanceof Error ? openError.message : "加载会话失败";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [hydrateThreadMessages]);

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

  const updateCurrentModelProfile = useCallback(
    async (nextModelProfileKey: string) => {
      setSelectedModelProfileKey(nextModelProfileKey);

      if (!isAuthenticated || !currentThreadIsPersisted) {
        return;
      }

      const previousModelProfileKey = selectedModelProfileKey;
      try {
        await updateSessionModelProfile(threadId, { model_profile_key: nextModelProfileKey });
      } catch (updateError) {
        setSelectedModelProfileKey(previousModelProfileKey);
        const message = updateError instanceof Error ? updateError.message : "切换模型失败";
        setError(message);
      }
    },
    [currentThreadIsPersisted, isAuthenticated, selectedModelProfileKey, threadId],
  );

  const prepareSendIntent = useCallback(
    (text: string): SendIntentResult => {
      const normalized = text.trim();
      if (!normalized) {
        return { status: "blocked", reason: "empty" };
      }
      if (loading || requestInFlightRef.current) {
        return { status: "blocked", reason: "loading" };
      }
      if (!ready) {
        return { status: "blocked", reason: "not_ready" };
      }
      if (!isAuthenticated) {
        return { status: "auth_required", message: normalized };
      }
      return { status: "accepted", message: normalized };
    },
    [isAuthenticated, loading, ready],
  );

  async function executeSend(
    normalized: string,
    modelProfileKeyOverride?: string | null,
    resumeTarget?: PendingInterruptState | null,
  ): Promise<void> {
    requestInFlightRef.current = true;
    setError(null);
    const effectiveModelProfileKey = (modelProfileKeyOverride ?? selectedModelProfileKey) || null;

    const userMessageId = resumeTarget ? null : createMessageId();
    const assistantMessageId = resumeTarget?.assistant_message_id ?? createMessageId();
    const targetThreadId = resumeTarget?.thread_id ?? threadId;
    const streamedToolTraces: ToolTrace[] = [];
    const streamedStepGroups: StepGroup[] = [];
    const streamedRenderSegments: ChatRenderSegment[] = [];
    let streamedReasoningText = "";
    const seenCalled = new Set<string>();
    const seenReturned = new Set<string>();
    let hasValuesResult = false;
    let interrupted = false;
    let shouldHydratePersistedThread = false;

    if (resumeTarget) {
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantMessageId
            ? {
                ...item,
                status: "streaming",
              }
            : item,
        ),
      );
    } else {
      setMessages((prev) => [
        ...prev,
        { id: userMessageId!, role: "user", text: normalized },
        { id: assistantMessageId, role: "assistant", text: "", status: "streaming", versions: [], can_regenerate: false },
      ]);
      lastSubmittedMessageRef.current = normalized;
    }
    setLoading(true);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const patchAssistantMessage = (updater: (draft: ChatMessageItem) => ChatMessageItem) => {
      setMessages((prev) => prev.map((item) => (item.id === assistantMessageId ? updater(item) : item)));
    };

    const buildStreamingMeta = (draftMeta?: ChatMetaInfo): ChatMetaInfo => ({
      ...(draftMeta ?? fallbackMetaInfo),
      tool_traces: [...streamedToolTraces],
      step_groups: cloneStepGroups(streamedStepGroups),
      render_segments: cloneRenderSegments(streamedRenderSegments),
      reasoning_text: streamedReasoningText || draftMeta?.reasoning_text || null,
      reasoning_state: streamedReasoningText ? "streaming" : (draftMeta?.reasoning_state ?? null),
    });

    const buildSettledMeta = (draftMeta?: ChatMetaInfo): ChatMetaInfo => ({
      ...buildStreamingMeta(draftMeta),
      reasoning_state: streamedReasoningText ? "completed" : (draftMeta?.reasoning_state ?? null),
    });

    try {
      const handleEvent = (event: ChatStreamEvent) => {
        if (event.event === "interrupt") {
          interrupted = true;
          setPendingInterrupt({
            ...event.data,
            assistant_message_id: assistantMessageId,
            thread_id: targetThreadId,
            model_profile_key: effectiveModelProfileKey,
          });
          patchAssistantMessage((draft) => ({
            ...draft,
            text: event.data.question,
            interrupt: event.data,
            status: undefined,
            meta: buildSettledMeta(draft.meta),
          }));
          return;
        }

        if (event.event === "messages") {
          const chunk = extractMessageChunk(event.data.data);
          if (!chunk) {
            return;
          }

          const chunkText = contentToText(chunk.data.content);
          const chunkReasoningText = extractReasoningTextFromSerializedMessage(chunk);
          if (!chunkText && !chunkReasoningText) {
            return;
          }

          if (chunkReasoningText) {
            streamedReasoningText += chunkReasoningText;
          }

          if (chunkText) {
            appendTextSegment(streamedRenderSegments, chunkText);
          }
          patchAssistantMessage((draft) => ({
            ...draft,
            text: getVisibleTextFromSegments(streamedRenderSegments),
            interrupt: undefined,
            meta: buildStreamingMeta(draft.meta),
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
          for (const trace of newTraces) {
            applyToolTraceToPresentation(trace, streamedStepGroups, streamedRenderSegments);
          }
          patchAssistantMessage((draft) => ({
            ...draft,
            interrupt: undefined,
            meta: buildStreamingMeta(draft.meta),
            status: "streaming",
          }));
          return;
        }

        if (event.event === "values") {
          const finalPayload = buildFinalPayloadFromValues(
            event.data.data,
            getVisibleTextFromSegments(streamedRenderSegments),
            streamedToolTraces,
          );
          if (!finalPayload) {
            return;
          }

          const hasStableAssistantMessage = Boolean(finalPayload.assistant_message.trim());
          if (hasStableAssistantMessage) {
            hasValuesResult = true;
            shouldHydratePersistedThread = true;
            setPendingInterrupt(null);
          }
          patchAssistantMessage((draft) => ({
            ...draft,
            text: finalPayload.assistant_message || draft.text || getVisibleTextFromSegments(streamedRenderSegments),
            interrupt: undefined,
            status: "streaming",
            meta: finalPayload.meta,
          }));
          return;
        }

        if (event.event === "error") {
          patchAssistantMessage((draft) => ({
            ...draft,
            text:
              getVisibleTextFromSegments(streamedRenderSegments) ||
              draft.text ||
              "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。",
            status: undefined,
            meta: buildSettledMeta(draft.meta),
          }));
        }
      };

      if (resumeTarget) {
        await streamChatResume(
          {
            thread_id: targetThreadId,
            interrupt_id: resumeTarget.interrupt_id,
            answer: normalized,
            locale: "zh-CN",
            model_profile_key: effectiveModelProfileKey,
            session_meta: {},
          },
          { signal: abortController.signal, onEvent: handleEvent },
        );
      } else {
        await streamChat(
          {
            thread_id: targetThreadId,
            user_message: normalized,
            locale: "zh-CN",
            model_profile_key: effectiveModelProfileKey,
            session_meta: {},
          },
          { signal: abortController.signal, onEvent: handleEvent },
        );
      }

      if (!hasValuesResult && !interrupted) {
        patchAssistantMessage((draft) => ({
          ...draft,
          text: getVisibleTextFromSegments(streamedRenderSegments) || draft.text || "当前未拿到完整响应，请重试。",
          status: draft.status === "stopped" ? "stopped" : undefined,
          meta: buildSettledMeta(draft.meta),
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
          interrupt: draft.interrupt,
          meta: draft.meta ?? {
            ...fallbackMetaInfo,
            tool_traces: [...streamedToolTraces],
            step_groups: cloneStepGroups(streamedStepGroups),
            render_segments: cloneRenderSegments(streamedRenderSegments),
          },
        }));
        return;
      }

      patchAssistantMessage((draft) => ({
        ...draft,
        text:
          getVisibleTextFromSegments(streamedRenderSegments) ||
          draft.text ||
          "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。",
        status: undefined,
        interrupt: draft.interrupt,
        meta: buildSettledMeta(draft.meta),
      }));
    } finally {
      if (hasValuesResult && !interrupted) {
        patchAssistantMessage((draft) => ({
          ...draft,
          status: draft.status === "stopped" ? "stopped" : undefined,
        }));
      }
      requestInFlightRef.current = false;
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      setLoading(false);
      await refreshSessions();
      if (shouldHydratePersistedThread && activeThreadIdRef.current === targetThreadId) {
        try {
          await hydrateThreadMessages(targetThreadId);
        } catch {
          // 历史回填失败时保留当前流式结果，避免把已展示内容清空。
        }
      }
    }
  }

  async function sendMessage(
    text: string,
    options?: { modelProfileKey?: string | null },
  ): Promise<SendIntentResult> {
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

    if (intent.status !== "accepted") {
      return intent;
    }

    void executeSend(intent.message, options?.modelProfileKey, pendingInterrupt);
    return intent;
  }

  async function regenerateLatestAssistantMessage(messageId: string) {
    if (loading || !isAuthenticated) {
      return;
    }

    const targetThreadId = threadId;
    const targetMessageKey = `persisted-${messageId}`;
    const streamedToolTraces: ToolTrace[] = [];
    const streamedStepGroups: StepGroup[] = [];
    const streamedRenderSegments: ChatRenderSegment[] = [];
    let streamedReasoningText = "";
    const seenCalled = new Set<string>();
    const seenReturned = new Set<string>();
    let shouldHydratePersistedThread = false;
    let hasStableAssistantMessage = false;
    const previousAssistantSnapshot =
      messages.find((item) => item.id === targetMessageKey) ?? null;

    setError(null);
    setLoading(true);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const patchAssistantMessage = (updater: (draft: ChatMessageItem) => ChatMessageItem) => {
      setMessages((prev) => prev.map((item) => (item.id === targetMessageKey ? updater(item) : item)));
    };

    const buildStreamingMeta = (draftMeta?: ChatMetaInfo): ChatMetaInfo => ({
      ...(draftMeta ?? fallbackMetaInfo),
      tool_traces: [...streamedToolTraces],
      step_groups: cloneStepGroups(streamedStepGroups),
      render_segments: cloneRenderSegments(streamedRenderSegments),
      reasoning_text: streamedReasoningText || draftMeta?.reasoning_text || null,
      reasoning_state: streamedReasoningText ? "streaming" : (draftMeta?.reasoning_state ?? null),
    });

    patchAssistantMessage((draft) => ({
      ...draft,
      status: "streaming",
      can_regenerate: false,
    }));

    try {
      await regenerateAssistantMessage(targetThreadId, messageId, {
        signal: abortController.signal,
        onEvent: (event) => {
          if (event.event === "messages") {
            const chunk = extractMessageChunk(event.data.data);
            if (!chunk) {
              return;
            }
            const chunkText = contentToText(chunk.data.content);
            const chunkReasoningText = extractReasoningTextFromSerializedMessage(chunk);
            if (!chunkText && !chunkReasoningText) {
              return;
            }
            if (chunkReasoningText) {
              streamedReasoningText += chunkReasoningText;
            }
            if (chunkText) {
              appendTextSegment(streamedRenderSegments, chunkText);
            }
            patchAssistantMessage((draft) => ({
              ...draft,
              text: getVisibleTextFromSegments(streamedRenderSegments),
              meta: buildStreamingMeta(draft.meta),
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
            for (const trace of newTraces) {
              applyToolTraceToPresentation(trace, streamedStepGroups, streamedRenderSegments);
            }
            patchAssistantMessage((draft) => ({
              ...draft,
              meta: buildStreamingMeta(draft.meta),
              status: "streaming",
            }));
            return;
          }

          if (event.event === "values") {
            const finalPayload = buildFinalPayloadFromValues(
              event.data.data,
              getVisibleTextFromSegments(streamedRenderSegments),
              streamedToolTraces,
            );
            if (!finalPayload) {
              return;
            }

            const nextHasStableAssistantMessage = Boolean(finalPayload.assistant_message.trim());
            if (nextHasStableAssistantMessage) {
              hasStableAssistantMessage = true;
              shouldHydratePersistedThread = true;
            }

            // Keep status as "streaming" — the stream may have more nodes to emit.
            // Status is cleared only after the stream fully resolves (in the finally block).
            patchAssistantMessage((draft) => ({
              ...draft,
              text:
                finalPayload.assistant_message ||
                draft.text ||
                getVisibleTextFromSegments(streamedRenderSegments),
              status: "streaming",
              meta: finalPayload.meta,
            }));
            return;
          }

          if (event.event === "error") {
            return;
          }
        },
      });
    } catch (regenerateError) {
      if (
        (regenerateError instanceof DOMException && regenerateError.name === "AbortError") ||
        (regenerateError instanceof Error && regenerateError.name === "AbortError")
      ) {
        return;
      }

    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      setLoading(false);
      await refreshSessions();
      // Stream fully ended — clear streaming status now that we know whether we succeeded.
      if (hasStableAssistantMessage) {
        patchAssistantMessage((draft) => ({
          ...draft,
          status: draft.status === "stopped" ? "stopped" : undefined,
        }));
      }
      if (!hasStableAssistantMessage && previousAssistantSnapshot) {
        setMessages((prev) =>
          prev.map((item) =>
            item.id === targetMessageKey
              ? {
                  ...previousAssistantSnapshot,
                  status: undefined,
                }
              : item,
          ),
        );
      }
      if (shouldHydratePersistedThread && activeThreadIdRef.current === targetThreadId) {
        try {
          await hydrateThreadMessages(targetThreadId);
        } catch {
          // 保留当前可见结果，不因回填失败清空消息。
        }
      }
    }
  }

  async function selectAssistantVersion(messageId: string, versionId: string) {
    const targetThreadId = threadId;
    await switchAssistantVersion(targetThreadId, messageId, { version_id: versionId });
    if (activeThreadIdRef.current === targetThreadId) {
      await hydrateThreadMessages(targetThreadId);
    }
    await refreshSessions();
  }

  async function setAssistantFeedback(messageId: string, versionId: string, feedback: AssistantVersionFeedback) {
    const targetThreadId = threadId;
    await updateAssistantFeedback(targetThreadId, messageId, versionId, { feedback });
    if (activeThreadIdRef.current === targetThreadId) {
      await hydrateThreadMessages(targetThreadId);
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

  useEffect(() => {
    if (!ready || !isAuthenticated || loading) {
      return;
    }
    const pendingIntent = consumePendingAuthMessage();
    if (!pendingIntent) {
      return;
    }
    if (pendingIntent.model_profile_key) {
      setSelectedModelProfileKey(pendingIntent.model_profile_key);
    }
    void sendMessage(pendingIntent.message, {
      modelProfileKey: pendingIntent.model_profile_key ?? null,
    });
  }, [isAuthenticated, loading, ready]);

  return {
    threadId,
    messages,
    pendingInterrupt,
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
