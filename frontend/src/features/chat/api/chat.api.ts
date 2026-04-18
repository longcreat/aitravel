import type {
  ChatInvokeRequest,
  ChatStreamEvent,
  ListChatModelProfilesResponse,
  PersistedChatMessage,
  SessionDetail,
  SessionModelProfileState,
  SessionSummary,
  SwitchAssistantVersionRequest,
  UpdateSessionModelProfileRequest,
  UpdateAssistantFeedbackRequest,
} from "@/features/chat/model/chat.types";
import { getStoredAccessToken } from "@/features/auth/model/auth.storage";
import { env } from "@/shared/config/env";
import { http } from "@/shared/lib/http";

type StreamEventName = ChatStreamEvent["event"];

interface StreamChatOptions {
  onEvent: (event: ChatStreamEvent) => void;
  signal?: AbortSignal;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const bodyText = await response.text();
    throw new Error(bodyText || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

const knownEventNames: StreamEventName[] = ["messages", "updates", "values", "error"];

function isKnownEventName(name: string): name is StreamEventName {
  return knownEventNames.includes(name as StreamEventName);
}

function parseSseBlock(block: string): { event: string; data: string } | null {
  const lines = block.split(/\r?\n/);
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!dataLines.length) {
    return null;
  }
  return { event: eventName, data: dataLines.join("\n") };
}

function toStreamEvent(eventName: string, rawData: string): ChatStreamEvent | null {
  if (!isKnownEventName(eventName)) {
    return null;
  }

  const parsed = JSON.parse(rawData) as ChatStreamEvent["data"];
  return {
    event: eventName,
    data: parsed,
  } as ChatStreamEvent;
}

export async function streamChat(payload: ChatInvokeRequest, options: StreamChatOptions): Promise<void> {
  return streamSse("/api/chat/stream", payload, options);
}

export async function listChatModelProfiles(): Promise<ListChatModelProfilesResponse> {
  return http.get<ListChatModelProfilesResponse>("/api/chat/model-profiles");
}

async function streamSse(path: string, payload: unknown, options: StreamChatOptions): Promise<void> {
  const accessToken = getStoredAccessToken();
  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(payload),
    signal: options.signal,
  });

  if (!response.ok) {
    const bodyText = await response.text();
    throw new Error(bodyText || `HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    while (true) {
      const boundary = buffer.indexOf("\n\n");
      if (boundary < 0) {
        break;
      }

      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const parsedBlock = parseSseBlock(block);
      if (!parsedBlock) {
        continue;
      }

      const streamEvent = toStreamEvent(parsedBlock.event, parsedBlock.data);
      if (!streamEvent) {
        continue;
      }
      options.onEvent(streamEvent);
    }
  }

  // 处理最后一个没有换行结束的分片。
  const tail = parseSseBlock(buffer);
  if (!tail) {
    return;
  }
  const streamEvent = toStreamEvent(tail.event, tail.data);
  if (streamEvent) {
    options.onEvent(streamEvent);
  }
}

export async function regenerateAssistantMessage(
  threadId: string,
  messageId: number,
  options: StreamChatOptions,
): Promise<void> {
  return streamSse(`/api/sessions/${encodeURIComponent(threadId)}/messages/${messageId}/regenerate/stream`, undefined, options);
}

export async function listSessions(): Promise<SessionSummary[]> {
  return http.get<SessionSummary[]>("/api/sessions");
}

export async function getSession(threadId: string): Promise<SessionDetail> {
  return http.get<SessionDetail>(`/api/sessions/${encodeURIComponent(threadId)}`);
}

export async function renameSession(threadId: string, title: string): Promise<SessionSummary> {
  return http.patch<SessionSummary>(`/api/sessions/${encodeURIComponent(threadId)}`, { title });
}

export async function deleteSession(threadId: string): Promise<void> {
  return http.delete<void>(`/api/sessions/${encodeURIComponent(threadId)}`);
}

export async function updateSessionModelProfile(
  threadId: string,
  payload: UpdateSessionModelProfileRequest,
): Promise<SessionModelProfileState> {
  return http.patch<SessionModelProfileState>(
    `/api/sessions/${encodeURIComponent(threadId)}/model-profile`,
    payload,
  );
}

export async function switchAssistantVersion(
  threadId: string,
  messageId: number,
  payload: SwitchAssistantVersionRequest,
): Promise<PersistedChatMessage> {
  return http.patch<PersistedChatMessage>(
    `/api/sessions/${encodeURIComponent(threadId)}/messages/${messageId}/current-version`,
    payload,
  );
}

export async function updateAssistantFeedback(
  threadId: string,
  messageId: number,
  versionId: number,
  payload: UpdateAssistantFeedbackRequest,
): Promise<PersistedChatMessage> {
  return http.patch<PersistedChatMessage>(
    `/api/sessions/${encodeURIComponent(threadId)}/messages/${messageId}/versions/${versionId}/feedback`,
    payload,
  );
}
