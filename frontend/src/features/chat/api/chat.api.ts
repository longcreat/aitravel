import type { ChatInvokeRequest, ChatStreamEvent, SessionDetail, SessionSummary } from "@/features/chat/model/chat.types";
import { env } from "@/shared/config/env";

type StreamEventName = ChatStreamEvent["event"];

interface StreamChatOptions {
  onEvent: (event: ChatStreamEvent) => void;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const bodyText = await response.text();
    throw new Error(bodyText || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

const knownEventNames: StreamEventName[] = ["start", "token", "tool_called", "tool_returned", "final", "error", "done"];

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
  const response = await fetch(`${env.apiBaseUrl}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
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

export async function listSessions(): Promise<SessionSummary[]> {
  const response = await fetch(`${env.apiBaseUrl}/api/sessions`);
  return parseJsonResponse<SessionSummary[]>(response);
}

export async function getSession(threadId: string): Promise<SessionDetail> {
  const response = await fetch(`${env.apiBaseUrl}/api/sessions/${encodeURIComponent(threadId)}`);
  return parseJsonResponse<SessionDetail>(response);
}

export async function renameSession(threadId: string, title: string): Promise<SessionSummary> {
  const response = await fetch(`${env.apiBaseUrl}/api/sessions/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  return parseJsonResponse<SessionSummary>(response);
}

export async function deleteSession(threadId: string): Promise<void> {
  const response = await fetch(`${env.apiBaseUrl}/api/sessions/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
  await parseJsonResponse<{ deleted: boolean }>(response);
}
