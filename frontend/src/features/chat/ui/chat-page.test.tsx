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

  it("streams token, tool events and final text response", async () => {
    const stream = createSseStream([
      'event: messages\ndata: {"type":"messages","ns":[],"data":[{"type":"AIMessageChunk","data":{"content":"推荐你先去东京，","additional_kwargs":{},"response_metadata":{},"type":"AIMessageChunk","name":null,"id":"chunk-1","tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"tool_call_chunks":[],"chunk_position":null}},{"langgraph_node":"model"}]}\n\n',
      'event: messages\ndata: {"type":"messages","ns":[],"data":[{"type":"AIMessageChunk","data":{"content":"再去大阪。","additional_kwargs":{},"response_metadata":{},"type":"AIMessageChunk","name":null,"id":"chunk-2","tool_calls":[],"invalid_tool_calls":[],"usage_metadata":{"input_tokens":10,"output_tokens":6},"tool_call_chunks":[],"chunk_position":null}},{"langgraph_node":"model"}]}\n\n',
      'event: updates\ndata: {"type":"updates","ns":[],"data":{"model":{"messages":[{"type":"ai","data":{"content":"我先调用时间工具。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[{"name":"get_current_time","args":{},"id":"call-1","type":"tool_call"}],"invalid_tool_calls":[],"usage_metadata":null}}]}}}\n\n',
      'event: updates\ndata: {"type":"updates","ns":[],"data":{"tools":{"messages":[{"type":"tool","data":{"content":"当前时间为21:02:21","additional_kwargs":{},"response_metadata":{},"type":"tool","name":"get_current_time","id":null,"tool_call_id":"call-1","artifact":null,"status":"success"}}]}}}\n\n',
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"推荐你先去东京，再去大阪。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null}}]}}\n\n',
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

    const input = screen.getByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "帮我规划日本6天行程");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("推荐你先去东京，再去大阪。")).toBeInTheDocument();
    });

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

    const stream = createSseStream([
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"已切换到新会话","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null}}]}}\n\n',
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
    await userEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
    const renameInput = await screen.findByPlaceholderText("新的会话名称");
    await userEvent.clear(renameInput);
    await userEvent.type(renameInput, "重命名后的会话");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(sessions[0]?.title).toBe("重命名后的会话");
    });

    await userEvent.click(screen.getByRole("button", { name: "session-menu-thread-test-1" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "删除" }));
    await userEvent.click(screen.getByRole("button", { name: "确定删除" }));
    await waitFor(() => {
      expect(sessions.find((session) => session.thread_id === "thread-test-1")).toBeUndefined();
    });

    await userEvent.click(screen.getByRole("button", { name: "close-history" }));
    await userEvent.type(screen.getByPlaceholderText("发消息或按住说话"), "继续规划");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("已切换到新会话")).toBeInTheDocument();
    });

    const streamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/stream"));
    expect(streamCalls).toHaveLength(1);
    const streamPayload = JSON.parse(String(streamCalls[0][1]?.body ?? "{}")) as { thread_id?: string };
    expect(streamPayload.thread_id).toBe("thread-test-2");
  }, 15000);
});
