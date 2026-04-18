import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/features/auth/model/auth.context";
import { RequireAuthRoute } from "@/features/auth/ui/require-auth-route";
import { AuthPage } from "@/features/auth/ui/auth-page";
import {
  clearStoredAccessToken,
  clearStoredAuthUser,
  setStoredAccessToken,
  setStoredAuthUser,
} from "@/features/auth/model/auth.storage";
import { ChatPage } from "@/features/chat/ui/chat-page";
import { TabLayout } from "@/shared/layouts/tab-layout";

const { getCurrentLocationNameMock } = vi.hoisted(() => ({
  getCurrentLocationNameMock: vi.fn(),
}));

vi.mock("@/features/location/lib/amap-location", () => ({
  getCurrentLocationName: getCurrentLocationNameMock,
  getLocationFallbackMessage: () => "未拿到当前位置，已先按当前位置为你发起请求。",
}));

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

function renderChatPage(initialPath = "/chat") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/" element={<TabLayout />}>
            <Route index element={<ChatPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route element={<RequireAuthRoute />}>
              <Route path="profile" element={<div>profile-page</div>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("ChatPage", () => {
  afterEach(() => {
    cleanup();
    clearStoredAccessToken();
    clearStoredAuthUser();
    window.sessionStorage.clear();
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
    getCurrentLocationNameMock.mockReset();
    getCurrentLocationNameMock.mockResolvedValue(null);
  });

  it("shows brand title and login button for unauthenticated users", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    expect(screen.getByText("WANDER AI")).toBeInTheDocument();
    expect(screen.getByText("有什么可以帮忙的？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "quick-prompt-规划行程" })).toBeInTheDocument();
    expect(screen.queryByText("你好，我是你的 AI 旅行 Agent。告诉我目的地、时间或想了解的问题，我会结合工具给你建议。")).not.toBeInTheDocument();
    expect(screen.queryByText("对话")).not.toBeInTheDocument();
    expect(screen.queryByText("我的")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "login" })).toBeInTheDocument();
    });
  });

  it("opens auth modal when unauthenticated user clicks the login button", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const loginButton = await screen.findByRole("button", { name: "login" });
    await userEvent.click(loginButton);

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });
  });

  it("opens guest drawer for unauthenticated users", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "guest-new-session" })).toBeInTheDocument();
    });

    expect(screen.getByText("登录后查看历史会话")).toBeInTheDocument();
    expect(screen.getByText("新建会话")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "login-or-register" })).toBeInTheDocument();
  });

  it("opens auth modal from guest drawer call to action before entering auth page", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    const loginOrRegisterButton = await screen.findByRole("button", { name: "login-or-register" });
    await userEvent.click(loginOrRegisterButton);

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });

    const loginButton = await screen.findByRole("button", { name: "auth-gate-login" });
    await userEvent.click(loginButton);

    await waitFor(() => {
      expect(screen.getByText("登录或注册")).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("电子邮件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续" })).toBeInTheDocument();
  });

  it("opens auth modal for unauthenticated send and keeps pending message", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      text: async (): Promise<string> => "not found",
    }));

    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const input = screen.getByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "帮我规划日本6天行程");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe("帮我规划日本6天行程");
  });

  it("opens auth modal for unauthenticated quick prompt click and keeps pending message", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      text: async (): Promise<string> => "not found",
    }));

    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await userEvent.click(screen.getByRole("button", { name: "quick-prompt-查询天气" }));

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe("请查询我当前的位置今天天气。");
  });

  it("uses AMap location name in quick prompt message when location is available", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 404,
      text: async (): Promise<string> => "not found",
    }));

    getCurrentLocationNameMock.mockResolvedValueOnce("杭州市西湖区");
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await userEvent.click(screen.getByRole("button", { name: "quick-prompt-查询天气" }));

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe("请查询杭州市西湖区今天天气。");
  });

  it("opens auth modal from drawer profile entry for unauthenticated users", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    await userEvent.click(screen.getByRole("button", { name: "open-profile" }));

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });
    expect(screen.queryByText("profile-page")).not.toBeInTheDocument();
  });

  it("redirects unauthenticated direct profile visit back to chat and opens auth modal", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage("/profile");

    await waitFor(() => {
      expect(screen.getByText("登录或创建账户")).toBeInTheDocument();
    });

    expect(screen.getByText("WANDER AI")).toBeInTheDocument();
    expect(screen.queryByText("profile-page")).not.toBeInTheDocument();
  });

  it("opens register tab when choosing register from auth modal", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const loginButton = await screen.findByRole("button", { name: "login" });
    await userEvent.click(loginButton);
    const registerButton = await screen.findByRole("button", { name: "auth-gate-register" });
    await userEvent.click(registerButton);

    await waitFor(() => {
      expect(screen.getByText("登录或注册")).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("电子邮件")).toBeInTheDocument();
  });

  it("navigates to profile from drawer profile entry for authenticated users", async () => {
    setStoredAccessToken("token-profile");
    setStoredAuthUser({
      id: "user-1",
      email: "demo@example.com",
      nickname: "demo",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-1",
            email: "demo@example.com",
            nickname: "demo",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown[]> => [],
          text: async (): Promise<string> => "[]",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    await userEvent.click(await screen.findByRole("button", { name: "open-profile" }));

    await waitFor(() => {
      expect(screen.getByText("profile-page")).toBeInTheDocument();
    });
  });

  it("streams token, tool events and final text response for authenticated user", async () => {
    setStoredAccessToken("token-1");
    setStoredAuthUser({
      id: "user-1",
      email: "demo@example.com",
      nickname: "demo",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
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

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-1",
            email: "demo@example.com",
            nickname: "demo",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

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
    renderChatPage();

    expect(screen.getByText("WANDER AI")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "login" })).not.toBeInTheDocument();

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "帮我规划日本6天行程");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("推荐你先去东京，再去大阪。")).toBeInTheDocument();
    });

    const streamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/stream"));
    expect(streamCalls).toHaveLength(1);
  });

  it("keeps cached login state when /api/auth/me fails with a non-auth error", async () => {
    setStoredAccessToken("token-persist");
    setStoredAuthUser({
      id: "user-1",
      email: "demo@example.com",
      nickname: "demo",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: false,
          status: 500,
          json: async (): Promise<unknown> => ({ detail: "server error" }),
          text: async (): Promise<string> => "server error",
        };
      }

      if (url.includes("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown[]> => [],
          text: async (): Promise<string> => "[]",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });

    expect(window.localStorage.getItem("ai-travel-access-token")).toBe("token-persist");
    expect(screen.queryByRole("button", { name: "login" })).not.toBeInTheDocument();
  });

  it("clears cached login state when /api/auth/me returns 401", async () => {
    setStoredAccessToken("token-expired");
    setStoredAuthUser({
      id: "user-1",
      email: "demo@example.com",
      nickname: "demo",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: false,
          status: 401,
          json: async (): Promise<unknown> => ({ detail: "invalid token" }),
          text: async (): Promise<string> => "invalid token",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "login" })).toBeInTheDocument();
    });

    expect(window.localStorage.getItem("ai-travel-access-token")).toBeNull();
  });
});
