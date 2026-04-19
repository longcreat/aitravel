import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

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

const emptyMeta = {
  tool_traces: [],
  step_groups: [],
  render_segments: [],
  mcp_connected_servers: [],
  mcp_errors: [],
} as const;

const modelProfilesResponse = {
  default_profile_key: "standard",
  profiles: [
    { key: "standard", label: "普通", kind: "standard", is_default: true },
    { key: "thinking", label: "思考", kind: "thinking", is_default: false },
  ],
} as const;

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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="pathname">{location.pathname}</div>;
}

function renderChatPage(initialPath = "/chat") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <LocationProbe />
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/" element={<TabLayout />}>
            <Route index element={<ChatPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:threadId" element={<ChatPage />} />
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
    expect(screen.getByLabelText("电子邮件")).toBeInTheDocument();
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

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe(
      JSON.stringify({ message: "帮我规划日本6天行程", model_profile_key: null }),
    );
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

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe(
      JSON.stringify({ message: "最近天气怎么样，适合出去玩吗？", model_profile_key: null }),
    );
  });

  it("stores the selected model profile in pending auth message", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/chat/model-profiles")) {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => modelProfilesResponse,
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

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "model-profile-selector" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "model-profile-selector" }));
    expect(screen.getByText("选择模型")).toBeInTheDocument();
    expect(screen.getByText("快速响应")).toBeInTheDocument();
    expect(screen.getByText("深度推理")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "model-profile-option-standard" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: "model-profile-option-thinking" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "model-profile-option-thinking" })).not.toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "帮我想想周末去哪");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    expect(window.sessionStorage.getItem("ai-travel-pending-message")).toBe(
      JSON.stringify({ message: "帮我想想周末去哪", model_profile_key: "thinking" }),
    );
  });

  it("sends fixed quick prompt copy without reading location", async () => {
    setStoredAccessToken("token-quick-prompt");
    setStoredAuthUser({
      id: "user-quick-prompt",
      email: "quick-prompt@example.com",
      nickname: "quick",
      created_at: "2026-04-08T00:00:00Z",
      updated_at: "2026-04-08T00:00:00Z",
    });

    const stream = createSseStream([
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"已收到。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null}}]}}\n\n',
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: "user-quick-prompt",
            email: "quick-prompt@example.com",
            nickname: "quick",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
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

    await userEvent.click(screen.getByRole("button", { name: "quick-prompt-查询天气" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/chat/stream"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("最近天气怎么样，适合出去玩吗？"),
        }),
      );
    });
    expect(getCurrentLocationNameMock).not.toHaveBeenCalled();
  });

  it("sends the selected model profile with a new thread message", async () => {
    setStoredAccessToken("token-model");
    setStoredAuthUser({
      id: "user-model",
      email: "model@example.com",
      nickname: "model",
      created_at: "2026-04-08T00:00:00Z",
      updated_at: "2026-04-08T00:00:00Z",
    });

    const stream = createSseStream([
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"收到。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null}}]}}\n\n',
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/chat/model-profiles") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => modelProfilesResponse,
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-model",
            email: "model@example.com",
            nickname: "model",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
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

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "model-profile-selector" })).toHaveTextContent("普通");
    });

    await userEvent.click(screen.getByRole("button", { name: "model-profile-selector" }));
    expect(screen.getByRole("button", { name: "model-profile-option-standard" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "model-profile-option-thinking" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "model-profile-option-thinking" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "model-profile-selector" })).toHaveTextContent("思考");

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "你好");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/chat/stream"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"model_profile_key":"thinking"'),
        }),
      );
    });
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
    expect(screen.getByLabelText("电子邮件")).toBeInTheDocument();
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

  it("restores the current session from /chat/:threadId after refresh", async () => {
    setStoredAccessToken("token-restore");
    setStoredAuthUser({
      id: "user-restore",
      email: "restore@example.com",
      nickname: "restore",
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
            id: "user-restore",
            email: "restore@example.com",
            nickname: "restore",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "thread-saved-1",
              title: "杭州天气",
              created_at: "2026-04-08T00:00:00Z",
              updated_at: "2026-04-08T00:00:00Z",
              last_message_preview: "今天杭州天气怎么样",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/thread-saved-1") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "thread-saved-1",
            title: "杭州天气",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
            messages: [
              {
                id: "msg-1",
                role: "user",
                text: "今天杭州天气怎么样",
                meta: null,
                created_at: "2026-04-08T00:00:00Z",
              },
              {
                id: "msg-2",
                role: "assistant",
                text: "杭州今天多云，气温适中。",
                meta: { ...emptyMeta },
                current_version_id: "ver-21",
                versions: [
                  {
                    id: "ver-21",
                    version_index: 1,
                    kind: "original",
                    text: "杭州今天多云，气温适中。",
                    meta: { ...emptyMeta },
                    feedback: null,
                    speech_status: null,
                    created_at: "2026-04-08T00:00:01Z",
                  },
                ],
                can_regenerate: true,
                created_at: "2026-04-08T00:00:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/thread-saved-1");

    await waitFor(() => {
      expect(screen.getByText("今天杭州天气怎么样")).toBeInTheDocument();
    });

    expect(screen.getByText("杭州今天多云，气温适中。")).toBeInTheDocument();
  });

  it("starts a new session from the header without reopening the previous route thread", async () => {
    setStoredAccessToken("token-new-header");
    setStoredAuthUser({
      id: "user-header",
      email: "header@example.com",
      nickname: "header",
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
            id: "user-header",
            email: "header@example.com",
            nickname: "header",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "thread-old",
              title: "旧会话",
              created_at: "2026-04-08T00:00:00Z",
              updated_at: "2026-04-08T00:00:00Z",
              last_message_preview: "旧问题",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/thread-old") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "thread-old",
            title: "旧会话",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
            messages: [
              {
                id: "msg-old-user",
                role: "user",
                text: "旧问题",
                meta: null,
                created_at: "2026-04-08T00:00:00Z",
              },
              {
                id: "msg-old-assistant",
                role: "assistant",
                text: "旧回答",
                meta: { ...emptyMeta },
                current_version_id: "ver-old-1",
                versions: [],
                can_regenerate: true,
                created_at: "2026-04-08T00:00:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/thread-old");

    await waitFor(() => {
      expect(screen.getByText("旧回答")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "new-session" }));

    await waitFor(() => {
      expect(screen.getByTestId("pathname").textContent).toMatch(/^\/chat\/thread-test-/);
    });

    expect(screen.getByText("有什么可以帮忙的？")).toBeInTheDocument();
    expect(screen.queryByText("旧问题")).not.toBeInTheDocument();
    expect(screen.queryByText("旧回答")).not.toBeInTheDocument();
  });

  it("starts a new session from the drawer and closes the drawer", async () => {
    setStoredAccessToken("token-new-drawer");
    setStoredAuthUser({
      id: "user-drawer",
      email: "drawer@example.com",
      nickname: "drawer",
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
            id: "user-drawer",
            email: "drawer@example.com",
            nickname: "drawer",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "thread-old",
              title: "旧会话",
              created_at: "2026-04-08T00:00:00Z",
              updated_at: "2026-04-08T00:00:00Z",
              last_message_preview: "旧问题",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/thread-old") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "thread-old",
            title: "旧会话",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
            messages: [
              {
                id: "msg-old-user-2",
                role: "user",
                text: "旧问题",
                meta: null,
                created_at: "2026-04-08T00:00:00Z",
              },
              {
                id: "msg-old-assistant-2",
                role: "assistant",
                text: "旧回答",
                meta: { ...emptyMeta },
                current_version_id: "ver-old-2",
                versions: [],
                can_regenerate: true,
                created_at: "2026-04-08T00:00:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/thread-old");

    await waitFor(() => {
      expect(screen.getByText("旧回答")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    const drawerNewSessionButton = (await screen.findAllByRole("button", { name: "new-session" }))[0];
    await userEvent.click(drawerNewSessionButton);

    await waitFor(() => {
      expect(screen.getByTestId("pathname").textContent).toMatch(/^\/chat\/thread-test-/);
    });

    expect(screen.queryByRole("button", { name: "close-history-overlay" })).not.toBeInTheDocument();
    expect(screen.getByText("有什么可以帮忙的？")).toBeInTheDocument();
    expect(screen.queryByText("旧回答")).not.toBeInTheDocument();
  });

  it("switches sessions from the drawer without bouncing between two threads", async () => {
    setStoredAccessToken("token-switch");
    setStoredAuthUser({
      id: "user-switch",
      email: "switch@example.com",
      nickname: "switch",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const sessionDetailCalls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-switch",
            email: "switch@example.com",
            nickname: "switch",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "thread-a",
              title: "会话 A",
              created_at: "2026-04-08T00:00:00Z",
              updated_at: "2026-04-08T00:00:00Z",
              last_message_preview: "问题 A",
            },
            {
              thread_id: "thread-b",
              title: "会话 B",
              created_at: "2026-04-08T00:10:00Z",
              updated_at: "2026-04-08T00:10:00Z",
              last_message_preview: "问题 B",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/thread-a") && method === "GET") {
        sessionDetailCalls.push("thread-a");
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "thread-a",
            title: "会话 A",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
            messages: [
              {
                id: "msg-a-user",
                role: "user",
                text: "问题 A",
                meta: null,
                created_at: "2026-04-08T00:00:00Z",
              },
              {
                id: "msg-a-assistant",
                role: "assistant",
                text: "回答 A",
                meta: { ...emptyMeta },
                current_version_id: "ver-a-1",
                versions: [],
                can_regenerate: true,
                created_at: "2026-04-08T00:00:01Z",
              },
            ],
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/sessions/thread-b") && method === "GET") {
        sessionDetailCalls.push("thread-b");
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "thread-b",
            title: "会话 B",
            created_at: "2026-04-08T00:10:00Z",
            updated_at: "2026-04-08T00:10:00Z",
            messages: [
              {
                id: "msg-b-user",
                role: "user",
                text: "问题 B",
                meta: null,
                created_at: "2026-04-08T00:10:00Z",
              },
              {
                id: "msg-b-assistant",
                role: "assistant",
                text: "回答 B",
                meta: { ...emptyMeta },
                current_version_id: "ver-b-2",
                versions: [],
                can_regenerate: true,
                created_at: "2026-04-08T00:10:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/thread-a");

    await waitFor(() => {
      expect(screen.getByText("回答 A")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    await userEvent.click(await screen.findByRole("button", { name: /会话 B/ }));

    await waitFor(() => {
      expect(screen.getByText("回答 B")).toBeInTheDocument();
    });

    expect(screen.queryByText("回答 A")).not.toBeInTheDocument();
    expect(sessionDetailCalls).toEqual(["thread-a", "thread-b"]);
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
      'event: messages\ndata: {"type":"messages","ns":[],"data":[{"type":"AIMessageChunk","data":{"content":"我先帮你查找余杭区附近适合周末散心的景点。","additional_kwargs":{},"response_metadata":{},"type":"AIMessageChunk","name":null,"id":"chunk-1","tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"tool_call_chunks":[],"chunk_position":null}},{"langgraph_node":"model"}]}\n\n',
      'event: updates\ndata: {"type":"updates","ns":[],"data":{"model":{"messages":[{"type":"ai","data":{"content":"我先帮你查找余杭区附近适合周末散心的景点。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[{"name":"amap_search_spots","args":{"district":"余杭区"},"id":"call-1","type":"tool_call"}],"invalid_tool_calls":[],"usage_metadata":null}}]}}}\n\n',
      'event: updates\ndata: {"type":"updates","ns":[],"data":{"tools":{"messages":[{"type":"tool","data":{"content":"搜索到 3 个景点","additional_kwargs":{},"response_metadata":{},"type":"tool","name":"amap_search_spots","id":null,"tool_call_id":"call-1","artifact":null,"status":"success"}}]}}}\n\n',
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"我先帮你查找余杭区附近适合周末散心的景点。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[{"name":"amap_search_spots","args":{"district":"余杭区"},"id":"call-1","type":"tool_call"}],"invalid_tool_calls":[],"usage_metadata":null}},{"type":"tool","data":{"content":"搜索到 3 个景点","additional_kwargs":{},"response_metadata":{},"type":"tool","name":"amap_search_spots","id":null,"tool_call_id":"call-1","artifact":null,"status":"success"}}]}}\n\n',
      'event: messages\ndata: {"type":"messages","ns":[],"data":[{"type":"AIMessageChunk","data":{"content":"基于我的搜索，为你推荐良渚古城遗址公园、东明山森林公园和梦想小镇附近的慢行路线。","additional_kwargs":{},"response_metadata":{},"type":"AIMessageChunk","name":null,"id":"chunk-2","tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null,"tool_call_chunks":[],"chunk_position":null}},{"langgraph_node":"model"}]}\n\n',
      'event: values\ndata: {"type":"values","ns":[],"data":{"messages":[{"type":"ai","data":{"content":"我先帮你查找余杭区附近适合周末散心的景点。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[{"name":"amap_search_spots","args":{"district":"余杭区"},"id":"call-1","type":"tool_call"}],"invalid_tool_calls":[],"usage_metadata":null}},{"type":"tool","data":{"content":"搜索到 3 个景点","additional_kwargs":{},"response_metadata":{},"type":"tool","name":"amap_search_spots","id":null,"tool_call_id":"call-1","artifact":null,"status":"success"}},{"type":"ai","data":{"content":"基于我的搜索，为你推荐良渚古城遗址公园、东明山森林公园和梦想小镇附近的慢行路线。","additional_kwargs":{},"response_metadata":{},"type":"ai","name":null,"id":null,"tool_calls":[],"invalid_tool_calls":[],"usage_metadata":null}}]}}\n\n',
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
      expect(screen.getByText("我先帮你查找余杭区附近适合周末散心的景点。")).toBeInTheDocument();
    });

    const stepButtonLabel = await screen.findByText("amap search spots");
    const stepButton = stepButtonLabel.closest("button");
    expect(stepButton).not.toBeNull();
    expect(stepButton).toHaveTextContent("amap search spots");

    await waitFor(() => {
      expect(
        screen.getByText("基于我的搜索，为你推荐良渚古城遗址公园、东明山森林公园和梦想小镇附近的慢行路线。"),
      ).toBeInTheDocument();
    });

    await userEvent.click(stepButton!);
    expect(await screen.findByText("Summary")).toBeInTheDocument();
    expect(screen.getAllByText("amap search spots").length).toBeGreaterThan(0);
    expect(screen.getByText("搜索到 3 个景点")).toBeInTheDocument();

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

  it("keeps the previous assistant reply when regenerate fails", async () => {
    setStoredAccessToken("token-regenerate");
    setStoredAuthUser({
      id: "user-1",
      email: "demo@example.com",
      nickname: "demo",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const regenerateStream = createSseStream([
      'event: error\ndata: {"message":"重新生成失败"}\n\n',
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

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "t-1",
              title: "余杭周末散心",
              created_at: "2026-04-05T00:00:00Z",
              updated_at: "2026-04-05T00:00:00Z",
              last_message_preview: "推荐几个余杭附近适合周末散心的景点",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/t-1") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "t-1",
            title: "余杭周末散心",
            created_at: "2026-04-05T00:00:00Z",
            updated_at: "2026-04-05T00:00:00Z",
            messages: [
              {
                id: "msg-regen-user",
                role: "user",
                text: "推荐几个余杭附近适合周末散心的景点",
                meta: null,
                created_at: "2026-04-05T00:00:00Z",
              },
              {
                id: "msg-regen-assistant",
                role: "assistant",
                text: "旧的推荐结果",
                meta: { ...emptyMeta },
                current_version_id: "ver-regen-11",
                versions: [
                  {
                    id: "ver-regen-11",
                    version_index: 1,
                    kind: "original",
                    text: "旧的推荐结果",
                    meta: { ...emptyMeta },
                    feedback: null,
                    speech_status: null,
                    created_at: "2026-04-05T00:00:01Z",
                  },
                ],
                can_regenerate: true,
                created_at: "2026-04-05T00:00:01Z",
              },
            ],
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/sessions/t-1/messages/msg-regen-assistant/regenerate/stream") && method === "POST") {
        return {
          ok: true,
          status: 200,
          body: regenerateStream,
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

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "open-history" }));
    await userEvent.click(await screen.findByRole("button", { name: /余杭周末散心/ }));

    await waitFor(() => {
      expect(screen.getByText("旧的推荐结果")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "regenerate-message-persisted-msg-regen-assistant" }));

    await waitFor(() => {
      expect(screen.getByText("旧的推荐结果")).toBeInTheDocument();
    });
  });

  it("requests playback url and plays assistant speech", async () => {
    setStoredAccessToken("token-speech");
    setStoredAuthUser({
      id: "user-speech",
      email: "speech@example.com",
      nickname: "speech",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();

    class FakeAudio {
      src: string;

      constructor(src: string) {
        this.src = src;
      }

      play = play;
      pause = pause;
      addEventListener = vi.fn();
    }

    vi.stubGlobal("Audio", FakeAudio as unknown as typeof Audio);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-speech",
            email: "speech@example.com",
            nickname: "speech",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "t-1",
              title: "语音测试",
              created_at: "2026-04-05T00:00:00Z",
              updated_at: "2026-04-05T00:00:00Z",
              last_message_preview: "播报一下这段话",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/t-1/messages/msg-speech-assistant/versions/ver-speech-11/speech/playback-url") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            playback_url: "http://localhost:8000/api/speech/play/token-ver-speech-11",
            speech_status: "ready",
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/sessions/t-1") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "t-1",
            title: "语音测试",
            created_at: "2026-04-05T00:00:00Z",
            updated_at: "2026-04-05T00:00:00Z",
            messages: [
              {
                id: "msg-speech-user",
                role: "user",
                text: "播报一下这段话",
                meta: null,
                created_at: "2026-04-05T00:00:00Z",
              },
              {
                id: "msg-speech-assistant",
                role: "assistant",
                text: "这是一段可以播报的回复。",
                meta: { ...emptyMeta },
                current_version_id: "ver-speech-11",
                versions: [
                  {
                    id: "ver-speech-11",
                    version_index: 1,
                    kind: "original",
                    text: "这是一段可以播报的回复。",
                    meta: { ...emptyMeta },
                    feedback: null,
                    speech_status: "ready",
                    speech_mime_type: "audio/mpeg",
                    created_at: "2026-04-05T00:00:01Z",
                  },
                ],
                can_regenerate: true,
                created_at: "2026-04-05T00:00:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/t-1");

    await waitFor(() => {
      expect(screen.getByText("这是一段可以播报的回复。")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "play-speech-message-persisted-msg-speech-assistant" }));

    await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/sessions/t-1/messages/msg-speech-assistant/versions/ver-speech-11/speech/playback-url"),
        expect.objectContaining({ method: "GET" }),
      );
      expect(play).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "stop-speech-message-persisted-msg-speech-assistant" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "stop-speech-message-persisted-msg-speech-assistant" }));
    expect(pause).toHaveBeenCalled();
  });

  it("refreshes the current thread after a 409 playback conflict and hides the speech button", async () => {
    setStoredAccessToken("token-speech-conflict");
    setStoredAuthUser({
      id: "user-speech-conflict",
      email: "speech-conflict@example.com",
      nickname: "speech-conflict",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    let sessionDetailCallCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-speech-conflict",
            email: "speech-conflict@example.com",
            nickname: "speech-conflict",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.endsWith("/api/sessions") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => [
            {
              thread_id: "t-1",
              title: "语音冲突测试",
              created_at: "2026-04-05T00:00:00Z",
              updated_at: "2026-04-05T00:00:00Z",
              last_message_preview: "播报按钮应该消失",
            },
          ],
          text: async (): Promise<string> => "[]",
        };
      }

      if (url.includes("/api/sessions/t-1/messages/msg-conflict-assistant/versions/ver-conflict-11/speech/playback-url") && method === "GET") {
        return {
          ok: false,
          status: 409,
          json: async (): Promise<unknown> => ({
            detail: "Speech asset unavailable",
          }),
          text: async (): Promise<string> => "Speech asset unavailable",
        };
      }

      if (url.includes("/api/sessions/t-1") && method === "GET") {
        sessionDetailCallCount += 1;
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            thread_id: "t-1",
            title: "语音冲突测试",
            created_at: "2026-04-05T00:00:00Z",
            updated_at: "2026-04-05T00:00:00Z",
            messages: [
              {
                id: "msg-conflict-user",
                role: "user",
                text: "播报按钮应该消失",
                meta: null,
                created_at: "2026-04-05T00:00:00Z",
              },
              {
                id: "msg-conflict-assistant",
                role: "assistant",
                text: "这是一段状态会失败的回复。",
                meta: { ...emptyMeta },
                current_version_id: "ver-conflict-11",
                versions: [
                  {
                    id: "ver-conflict-11",
                    version_index: 1,
                    kind: "original",
                    text: "这是一段状态会失败的回复。",
                    meta: { ...emptyMeta },
                    feedback: null,
                    speech_status: sessionDetailCallCount === 1 ? "ready" : "failed",
                    speech_mime_type: "audio/mpeg",
                    created_at: "2026-04-05T00:00:01Z",
                  },
                ],
                can_regenerate: true,
                created_at: "2026-04-05T00:00:01Z",
              },
            ],
          }),
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
    renderChatPage("/chat/t-1");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "play-speech-message-persisted-msg-conflict-assistant" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "play-speech-message-persisted-msg-conflict-assistant" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "play-speech-message-persisted-msg-conflict-assistant" })).not.toBeInTheDocument();
    });

    expect(sessionDetailCallCount).toBe(2);
  });
});
