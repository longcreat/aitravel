import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPage } from "@/features/chat/ui/chat-page";

function createSseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("ChatPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    let seed = 0;
    Object.defineProperty(globalThis, "crypto", {
      value: {
        randomUUID: () => {
          seed += 1;
          return `thread-test-${seed}`;
        },
      },
      configurable: true,
    });
  });

  it("streams token, tool events and final structured response", async () => {
    const stream = createSseStream([
      'event: start\ndata: {"thread_id":"thread-test-1","started_at":"2026-04-05T00:00:00Z"}\n\n',
      'event: token\ndata: {"chunk":{"id":"chunk-1","type":"AIMessageChunk","content":"推荐你先去东京，","name":null,"chunk_position":null,"tool_call_chunks":[],"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"response_metadata":{},"additional_kwargs":{}},"meta":{"node":"model","sequence":1,"emitted_at":"2026-04-05T00:00:01Z"}}\n\n',
      'event: token\ndata: {"chunk":{"id":"chunk-2","type":"AIMessageChunk","content":"再去大阪。","name":null,"chunk_position":null,"tool_call_chunks":[],"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":{"input_tokens":10,"output_tokens":6},"response_metadata":{},"additional_kwargs":{}},"meta":{"node":"model","sequence":2,"emitted_at":"2026-04-05T00:00:02Z"}}\n\n',
      'event: tool_called\ndata: {"tool_name":"estimate_trip_budget","payload":{"days":6}}\n\n',
      'event: tool_returned\ndata: {"tool_name":"estimate_trip_budget","payload":"预算约5400元"}\n\n',
      'event: final\ndata: {"assistant_message":"推荐你先去东京，再去大阪。","itinerary":[{"day":1,"city":"Tokyo","activities":["浅草寺","上野公园"]}],"followups":["你更偏好购物还是美食？"],"debug":{"tool_traces":[{"phase":"called","tool_name":"estimate_trip_budget","payload":{"days":6}},{"phase":"returned","tool_name":"estimate_trip_budget","payload":"预算约5400元"}],"mcp_connected_servers":[],"mcp_errors":[]}}\n\n',
      "event: done\ndata: {}\n\n",
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown[]> => [],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/chat/stream") && method === "POST") {
        return {
          ok: true,
          status: 200,
          body: stream,
          text: async (): Promise<string> => "",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<ChatPage />);

    const input = screen.getByPlaceholderText("例如：6月去东京7天，预算1.2万，2人，偏美食和慢节奏");
    await userEvent.type(input, "帮我规划日本6天行程");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("推荐你先去东京，再去大阪。")).toBeInTheDocument();
    });

    expect(screen.getByText("结构化行程")).toBeInTheDocument();
    expect(screen.queryByText("Chunk Frames")).not.toBeInTheDocument();
    const streamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/stream"));
    expect(streamCalls).toHaveLength(1);
  });

  it("shows grouped history and supports rename/delete for current session", async () => {
    const now = new Date();
    const dayMs = 24 * 60 * 60 * 1000;
    const sessions = [
      {
        thread_id: "thread-test-1",
        title: "今天会话",
        created_at: now.toISOString(),
        updated_at: now.toISOString(),
        last_message_preview: "你好",
      },
      {
        thread_id: "thread-7d",
        title: "近7天会话",
        created_at: new Date(now.getTime() - 3 * dayMs).toISOString(),
        updated_at: new Date(now.getTime() - 3 * dayMs).toISOString(),
        last_message_preview: "近7天",
      },
      {
        thread_id: "thread-30d",
        title: "近30天会话",
        created_at: new Date(now.getTime() - 10 * dayMs).toISOString(),
        updated_at: new Date(now.getTime() - 10 * dayMs).toISOString(),
        last_message_preview: "近30天",
      },
      {
        thread_id: "thread-old",
        title: "更早会话",
        created_at: new Date(now.getTime() - 45 * dayMs).toISOString(),
        updated_at: new Date(now.getTime() - 45 * dayMs).toISOString(),
        last_message_preview: "历史消息",
      },
    ];

    const promptMock = vi.spyOn(window, "prompt").mockReturnValue("重命名后的会话");
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);

    const stream = createSseStream([
      'event: start\ndata: {"thread_id":"thread-test-2","started_at":"2026-04-05T00:00:00Z"}\n\n',
      'event: final\ndata: {"assistant_message":"已切换到新会话","itinerary":[],"followups":[],"debug":{"tool_traces":[],"mcp_connected_servers":[],"mcp_errors":[]}}\n\n',
      "event: done\ndata: {}\n\n",
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/sessions") && method === "GET" && !url.match(/\/api\/sessions\/[^/]+$/)) {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => sessions,
          text: async (): Promise<string> => JSON.stringify(sessions),
        };
      }

      if (url.includes("/api/sessions/thread-test-1") && method === "PATCH") {
        const body = JSON.parse(String(init?.body ?? "{}")) as { title?: string };
        sessions[0] = { ...sessions[0], title: body.title ?? sessions[0].title };
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => sessions[0],
          text: async (): Promise<string> => JSON.stringify(sessions[0]),
        };
      }

      if (url.includes("/api/sessions/thread-test-1") && method === "DELETE") {
        sessions.splice(0, 1);
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({ deleted: true }),
          text: async (): Promise<string> => '{"deleted":true}',
        };
      }

      if (url.includes("/api/chat/stream") && method === "POST") {
        return {
          ok: true,
          status: 200,
          body: stream,
          text: async (): Promise<string> => "",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);
    render(<ChatPage />);

    await userEvent.click(screen.getAllByRole("button", { name: "open-history" })[0]);

    expect(screen.getByText("今日")).toBeInTheDocument();
    expect(screen.getByText("7日")).toBeInTheDocument();
    expect(screen.getByText("30日")).toBeInTheDocument();
    expect(screen.getByText("更早")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "session-menu-thread-test-1" }));
    await userEvent.click(screen.getByRole("button", { name: "重命名" }));
    await waitFor(() => {
      expect(promptMock).toHaveBeenCalledTimes(1);
      expect(sessions[0]?.title).toBe("重命名后的会话");
    });

    await userEvent.click(screen.getByRole("button", { name: "session-menu-thread-test-1" }));
    await userEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => {
      expect(confirmMock).toHaveBeenCalledTimes(1);
    });

    await userEvent.click(screen.getByRole("button", { name: "close-history" }));
    await userEvent.type(screen.getByPlaceholderText("例如：6月去东京7天，预算1.2万，2人，偏美食和慢节奏"), "继续规划");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("已切换到新会话")).toBeInTheDocument();
    });

    const streamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/stream"));
    expect(streamCalls).toHaveLength(1);
    const streamPayload = JSON.parse(String(streamCalls[0][1]?.body ?? "{}")) as { thread_id?: string };
    expect(streamPayload.thread_id).toBe("thread-test-2");
  });
});
