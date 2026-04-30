import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

function createControlledSseStream() {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(nextController) {
      controller = nextController;
    },
  });

  return {
    stream,
    enqueue(chunk: string) {
      controller?.enqueue(encoder.encode(chunk));
    },
    close() {
      controller?.close();
    },
  };
}

function sseEvent(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function textPart(id: string, text: string, status = "completed") {
  return { id, type: "text", text, status };
}

function userMessage(id: string, text: string, createdAt = "2026-04-08T00:00:00Z") {
  return {
    id,
    role: "user",
    text,
    parts: [textPart(`${id}-text`, text)],
    status: "completed",
    meta: null,
    created_at: createdAt,
  };
}

function assistantMessage({
  id,
  versionId,
  text = "",
  parts = [],
  status = "completed",
  meta = emptyMeta,
  canRegenerate = true,
  createdAt = "2026-04-08T00:00:01Z",
}: {
  id: string;
  versionId: string;
  text?: string;
  parts?: unknown[];
  status?: string;
  meta?: unknown;
  canRegenerate?: boolean;
  createdAt?: string;
}) {
  return {
    id,
    role: "assistant",
    text,
    parts,
    status,
    meta,
    current_version_id: versionId,
    versions: [
      {
        id: versionId,
        version_index: 1,
        kind: "original",
        text,
        parts,
        status,
        meta,
        feedback: null,
        speech_status: null,
        created_at: createdAt,
      },
    ],
    can_regenerate: canRegenerate,
    created_at: createdAt,
  };
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
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-quick-user", "最近天气怎么样，适合出去玩吗？"),
        assistant_message: assistantMessage({ id: "msg-quick-assistant", versionId: "ver-quick-1", status: "streaming" }),
      }),
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-quick-assistant",
          versionId: "ver-quick-1",
          text: "已收到。",
          parts: [textPart("text-1", "已收到。")],
        }),
      }),
      sseEvent("turn.done", { thread_id: "thread-test-1" }),
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
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-model-user", "帮我想一个深度行程"),
        assistant_message: assistantMessage({ id: "msg-model-assistant", versionId: "ver-model-1", status: "streaming" }),
      }),
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-model-assistant",
          versionId: "ver-model-1",
          text: "收到。",
          parts: [textPart("text-1", "收到。")],
        }),
      }),
      sseEvent("turn.done", { thread_id: "thread-test-1" }),
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
    const firstText = "我先帮你查找余杭区附近适合周末散心的景点。";
    const finalText = "基于我的搜索，为你推荐良渚古城遗址公园、东明山森林公园和梦想小镇附近的慢行路线。";
    const toolPart = {
      id: "tool-call-1",
      type: "tool",
      tool_call_id: "call-1",
      tool_name: "amap_search_spots",
      input: { district: "余杭区" },
      output: "搜索到 3 个景点",
      status: "success",
    };
    const stream = createSseStream([
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-stream-user", "帮我规划日本6天行程"),
        assistant_message: assistantMessage({ id: "msg-stream-assistant", versionId: "ver-stream-1", status: "streaming" }),
      }),
      sseEvent("part.delta", {
        message_id: "msg-stream-assistant",
        version_id: "ver-stream-1",
        part_id: "text-1",
        part_type: "text",
        text_delta: firstText,
        status: "streaming",
      }),
      sseEvent("tool.start", {
        message_id: "msg-stream-assistant",
        version_id: "ver-stream-1",
        part: { ...toolPart, output: undefined, status: "running" },
      }),
      sseEvent("tool.done", {
        message_id: "msg-stream-assistant",
        version_id: "ver-stream-1",
        part: toolPart,
      }),
      sseEvent("part.delta", {
        message_id: "msg-stream-assistant",
        version_id: "ver-stream-1",
        part_id: "text-2",
        part_type: "text",
        text_delta: finalText,
        status: "streaming",
      }),
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-stream-assistant",
          versionId: "ver-stream-1",
          text: `${firstText}${finalText}`,
          parts: [textPart("text-1", firstText), toolPart, textPart("text-2", finalText)],
        }),
      }),
      sseEvent("turn.done", { thread_id: "thread-test-1" }),
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
    expect(await screen.findByText("返回结果")).toBeInTheDocument();
    expect(screen.getAllByText("amap search spots").length).toBeGreaterThan(0);
    expect(screen.getByText("搜索到 3 个景点")).toBeInTheDocument();

    const streamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/stream"));
    expect(streamCalls).toHaveLength(1);
  });

  it("keeps streamed tool parts between text chunks when a text part continues after the tool", async () => {
    setStoredAccessToken("token-order");
    setStoredAuthUser({
      id: "user-order",
      email: "order@example.com",
      nickname: "order",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const controlledStream = createControlledSseStream();
    const toolPart = {
      id: "tool-call-order-1",
      type: "tool",
      tool_call_id: "call-order-1",
      tool_name: "amap_search_spots",
      input: { district: "余杭区" },
      status: "running",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-order",
            email: "order@example.com",
            nickname: "order",
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
          body: controlledStream.stream,
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

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "查一下周边景点");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    controlledStream.enqueue(
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-order-user", "查一下周边景点"),
        assistant_message: assistantMessage({ id: "msg-order-assistant", versionId: "ver-order-1", status: "streaming" }),
      }),
    );
    controlledStream.enqueue(
      sseEvent("part.delta", {
        message_id: "msg-order-assistant",
        version_id: "ver-order-1",
        part_id: "text-1",
        part_type: "text",
        text_delta: "我先查一下。",
        status: "streaming",
      }),
    );
    controlledStream.enqueue(
      sseEvent("tool.start", {
        message_id: "msg-order-assistant",
        version_id: "ver-order-1",
        part: toolPart,
      }),
    );
    controlledStream.enqueue(
      sseEvent("part.delta", {
        message_id: "msg-order-assistant",
        version_id: "ver-order-1",
        part_id: "text-1",
        part_type: "text",
        text_delta: "查完后给你路线。",
        status: "streaming",
      }),
    );

    await waitFor(() => {
      expect(screen.getByText("我先查一下。")).toBeInTheDocument();
      expect(screen.getByText("amap search spots")).toBeInTheDocument();
      expect(screen.getByText("查完后给你路线。")).toBeInTheDocument();
    });

    const renderedText = document.body.textContent ?? "";
    expect(renderedText.indexOf("我先查一下。")).toBeLessThan(renderedText.indexOf("amap search spots"));
    expect(renderedText.indexOf("amap search spots")).toBeLessThan(renderedText.indexOf("查完后给你路线。"));

    controlledStream.enqueue(
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-order-assistant",
          versionId: "ver-order-1",
          text: "我先查一下。查完后给你路线。",
          parts: [
            textPart("text-1", "我先查一下。"),
            { ...toolPart, output: "搜索到 3 个景点", status: "success" },
            textPart("text-2", "查完后给你路线。"),
          ],
        }),
      }),
    );
    controlledStream.enqueue(sseEvent("turn.done", { thread_id: "thread-test-1" }));
    controlledStream.close();
  });

  it("shows the running tool card before text when the first streamed part is a tool", async () => {
    setStoredAccessToken("token-tool-first");
    setStoredAuthUser({
      id: "user-tool-first",
      email: "tool-first@example.com",
      nickname: "tool-first",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const rafCallbacks: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      rafCallbacks.push(callback);
      return rafCallbacks.length;
    }));

    const controlledStream = createControlledSseStream();
    const runningToolPart = {
      id: "tool-call-weather-1",
      type: "tool",
      tool_call_id: "call-weather-1",
      tool_name: "amap-mcp-server_maps_weather",
      input: { city: "杭州" },
      output: null,
      status: "running",
    };
    const successToolPart = {
      ...runningToolPart,
      output: "杭州未来 4 天天气",
      status: "success",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-tool-first",
            email: "tool-first@example.com",
            nickname: "tool-first",
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
          body: controlledStream.stream,
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

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "杭州天气查询");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    controlledStream.enqueue(
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-tool-first-user", "杭州天气查询"),
        assistant_message: assistantMessage({ id: "msg-tool-first-assistant", versionId: "ver-tool-first-1", status: "streaming" }),
      }) +
        sseEvent("tool.start", {
          message_id: "msg-tool-first-assistant",
          version_id: "ver-tool-first-1",
          part: runningToolPart,
        }) +
        sseEvent("tool.done", {
          message_id: "msg-tool-first-assistant",
          version_id: "ver-tool-first-1",
          part: successToolPart,
        }) +
        sseEvent("part.delta", {
          message_id: "msg-tool-first-assistant",
          version_id: "ver-tool-first-1",
          part_id: "text-1",
          part_type: "text",
          text_delta: "根据高德地图天气数据，杭州未来几天有雨。",
          status: "streaming",
        }) +
        sseEvent("message.completed", {
          message: assistantMessage({
            id: "msg-tool-first-assistant",
            versionId: "ver-tool-first-1",
            text: "根据高德地图天气数据，杭州未来几天有雨。",
            parts: [successToolPart, textPart("text-1", "根据高德地图天气数据，杭州未来几天有雨。")],
          }),
        }) +
        sseEvent("turn.done", { thread_id: "thread-test-1" }),
    );
    controlledStream.close();

    const toolButton = await screen.findByRole("button", {
      name: "open-tool-group-persisted-msg-tool-first-assistant-0",
    });
    expect(toolButton).toHaveTextContent("高德地图 · 天气查询");
    expect(toolButton.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("根据高德地图天气数据，杭州未来几天有雨。")).not.toBeInTheDocument();

    expect(rafCallbacks.length).toBeGreaterThan(0);
    for (const callback of rafCallbacks.splice(0)) {
      callback(performance.now());
    }

    await waitFor(() => {
      expect(toolButton.querySelector(".animate-spin")).toBeNull();
      expect(screen.getByText("根据高德地图天气数据，杭州未来几天有雨。")).toBeInTheDocument();
    });
  });

  it("preserves tool artifact payload from SSE updates and shows structured JSON in summary", async () => {
    setStoredAccessToken("token-exa");
    setStoredAuthUser({
      id: "user-exa",
      email: "exa@example.com",
      nickname: "exa",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const exaIntroText = "我先用 Exa 查一下京都攻略。";
    const exaFinalText = "我找到一篇不错的京都攻略。";
    const exaToolPart = {
      id: "tool-call-exa-1",
      type: "tool",
      tool_call_id: "call-exa-1",
      tool_name: "exa_web_search_advanced_exa",
      input: { query: "京都攻略", num_results: 3 },
      output: {
        kind: "exa_search",
        results: [{ title: "Kyoto Guide", url: "https://example.com/kyoto" }],
      },
      status: "success",
    };
    const stream = createSseStream([
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-exa-user", "帮我找一篇京都攻略"),
        assistant_message: assistantMessage({ id: "msg-exa-assistant", versionId: "ver-exa-1", status: "streaming" }),
      }),
      sseEvent("part.delta", {
        message_id: "msg-exa-assistant",
        version_id: "ver-exa-1",
        part_id: "text-1",
        part_type: "text",
        text_delta: exaIntroText,
        status: "streaming",
      }),
      sseEvent("tool.start", {
        message_id: "msg-exa-assistant",
        version_id: "ver-exa-1",
        part: { ...exaToolPart, output: undefined, status: "running" },
      }),
      sseEvent("tool.done", {
        message_id: "msg-exa-assistant",
        version_id: "ver-exa-1",
        part: exaToolPart,
      }),
      sseEvent("part.delta", {
        message_id: "msg-exa-assistant",
        version_id: "ver-exa-1",
        part_id: "text-2",
        part_type: "text",
        text_delta: exaFinalText,
        status: "streaming",
      }),
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-exa-assistant",
          versionId: "ver-exa-1",
          text: `${exaIntroText}${exaFinalText}`,
          parts: [textPart("text-1", exaIntroText), exaToolPart, textPart("text-2", exaFinalText)],
        }),
      }),
      sseEvent("turn.done", { thread_id: "thread-test-1" }),
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-exa",
            email: "exa@example.com",
            nickname: "exa",
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

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "帮我找一篇京都攻略");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(screen.getByText("我找到一篇不错的京都攻略。")).toBeInTheDocument();
    });

    const stepButtonLabel = await screen.findByText("Exa · 高级网络搜索");
    const stepButton = stepButtonLabel.closest("button");
    expect(stepButton).not.toBeNull();

    await userEvent.click(stepButton!);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/"kind": "exa_search"/)).toBeInTheDocument();
    expect(within(dialog).getByText(/"title": "Kyoto Guide"/)).toBeInTheDocument();
    expect(within(dialog).getByText(/"query": "京都攻略"/)).toBeInTheDocument();
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

  it("hides stream error details and keeps the generic assistant fallback", async () => {
    setStoredAccessToken("token-stream-error");
    setStoredAuthUser({
      id: "user-stream-error",
      email: "stream-error@example.com",
      nickname: "stream-error",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const friendlyFailureText = "当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。";
    const stream = createSseStream([
      sseEvent("turn.start", {
        thread_id: "thread-test-1",
        user_message: userMessage("msg-error-user", "今天的天气咋样"),
        assistant_message: assistantMessage({ id: "msg-error-assistant", versionId: "ver-error-1", status: "streaming" }),
      }),
      sseEvent("message.completed", {
        message: assistantMessage({
          id: "msg-error-assistant",
          versionId: "ver-error-1",
          text: friendlyFailureText,
          parts: [textPart("text-1", friendlyFailureText, "failed")],
          status: "failed",
          canRegenerate: false,
        }),
      }),
      sseEvent("error", { message: "请求失败，请稍后重试。" }),
    ]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-stream-error",
            email: "stream-error@example.com",
            nickname: "stream-error",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
          text: async (): Promise<string> => "",
        };
      }

      if (url.includes("/api/chat/model-profiles") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => modelProfilesResponse,
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
      expect(screen.getByRole("button", { name: "new-session" })).toBeInTheDocument();
    });

    const input = await screen.findByPlaceholderText("发消息或按住说话");
    await userEvent.type(input, "今天的天气咋样");
    await userEvent.click(screen.getByRole("button", { name: "send-message" }));

    await waitFor(() => {
      expect(
        screen.getByText("当前请求失败，可能是网络或后端服务异常。你可以重试，或先告诉我你希望去哪里。"),
      ).toBeInTheDocument();
    });

    expect(screen.queryByText("请求失败：")).not.toBeInTheDocument();
    expect(screen.queryByText("请求失败，请稍后重试。")).not.toBeInTheDocument();
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
      sseEvent("turn.start", {
        thread_id: "t-1",
        assistant_message: assistantMessage({ id: "msg-regen-assistant", versionId: "ver-regen-12", status: "streaming" }),
      }),
      sseEvent("error", { message: "重新生成失败" }),
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
                parts: [textPart("text-1", "旧的推荐结果")],
                status: "completed",
                meta: { ...emptyMeta },
                current_version_id: "ver-regen-11",
                versions: [
                  {
                    id: "ver-regen-11",
                    version_index: 1,
                    kind: "original",
                    text: "旧的推荐结果",
                    parts: [textPart("text-1", "旧的推荐结果")],
                    status: "completed",
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

    expect(screen.queryByText("请求失败：")).not.toBeInTheDocument();
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
