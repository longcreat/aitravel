import type { ReactElement } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatMetaInfo, ChatMessageItem } from "@/features/chat/model/chat.types";
import { ChatMessage } from "@/features/chat/ui/chat-message";
import { AppSurfaceOverlayRootContext } from "@/shared/layouts/app-surface-overlay";

const emptyMeta: ChatMetaInfo = {
  mcp_connected_servers: [],
  mcp_errors: [],
};

function textPart(id: string, text: string, status: "streaming" | "completed" | "stopped" | "failed" = "completed") {
  return { id, type: "text" as const, text, status };
}

function reasoningPart(id: string, text: string, status: "streaming" | "completed" | "stopped" | "failed" = "completed") {
  return { id, type: "reasoning" as const, text, status };
}

function toolPart(
  id: string,
  toolName: string,
  options?: {
    input?: unknown;
    output?: unknown;
    status?: "running" | "success" | "error";
    toolCallId?: string;
  },
) {
  return {
    id,
    type: "tool" as const,
    tool_call_id: options?.toolCallId ?? id,
    tool_name: toolName,
    input: options?.input,
    output: options?.output,
    status: options?.status ?? "success",
  };
}

function renderWithOverlayRoot(ui: ReactElement) {
  const overlayRoot = document.createElement("div");
  document.body.appendChild(overlayRoot);
  return {
    overlayRoot,
    ...render(
      <AppSurfaceOverlayRootContext.Provider value={overlayRoot}>
        {ui}
      </AppSurfaceOverlayRootContext.Provider>,
    ),
  };
}

describe("ChatMessage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("shows copy button for assistant message and copies final text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", {
      clipboard: {
        writeText,
      },
    });

    const message: ChatMessageItem = {
      id: "assistant-1",
      role: "assistant",
      text: "这是最终回复正文。",
      meta: { ...emptyMeta },
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    const copyButton = screen.getByRole("button", { name: "copy-message-assistant-1" });
    await userEvent.click(copyButton);

    expect(writeText).toHaveBeenCalledWith("这是最终回复正文。");
    expect(screen.queryByText("已复制")).not.toBeInTheDocument();
  });

  it("does not show copy button for user message", () => {
    const message: ChatMessageItem = {
      id: "user-1",
      role: "user",
      text: "帮我规划一下路线。",
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.queryByRole("button", { name: "copy-message-user-1" })).not.toBeInTheDocument();
  });

  it("shows icon-only assistant actions for persisted latest reply and wires callbacks", async () => {
    const onRegenerate = vi.fn();
    const onSwitchVersion = vi.fn();
    const onFeedback = vi.fn();
    const onToggleSpeech = vi.fn();

    const message: ChatMessageItem = {
      id: "persisted-msg-42",
      role: "assistant",
      text: "这是重生后的最终回复。",
      current_version_id: "ver-1002",
      can_regenerate: true,
      meta: { ...emptyMeta },
      versions: [
        {
          id: "ver-1001",
          version_index: 1,
          kind: "original",
          text: "这是原始版本。",
          meta: null,
          feedback: null,
          speech_status: null,
          created_at: "2026-04-07T00:00:00+08:00",
        },
        {
          id: "ver-1002",
          version_index: 2,
          kind: "regenerated",
          text: "这是重生后的最终回复。",
          meta: null,
          feedback: "up",
          speech_status: "ready",
          speech_mime_type: "audio/mpeg",
          created_at: "2026-04-07T00:01:00+08:00",
        },
      ],
    };

    renderWithOverlayRoot(
      <ChatMessage
        message={message}
        onRegenerate={onRegenerate}
        onSwitchVersion={onSwitchVersion}
        onFeedback={onFeedback}
        onToggleSpeech={onToggleSpeech}
      />,
    );

    expect(screen.getByRole("button", { name: "copy-message-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "play-speech-message-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "regenerate-message-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "thumbs-up-message-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "thumbs-down-message-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "previous-version-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "next-version-persisted-msg-42" })).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
    expect(screen.queryByText("复制")).not.toBeInTheDocument();
    expect(screen.queryByText("重新生成")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "regenerate-message-persisted-msg-42" }));
    expect(onRegenerate).toHaveBeenCalledWith("msg-42");

    await userEvent.click(screen.getByRole("button", { name: "previous-version-persisted-msg-42" }));
    expect(onSwitchVersion).toHaveBeenCalledWith("msg-42", "ver-1001");

    await userEvent.click(screen.getByRole("button", { name: "play-speech-message-persisted-msg-42" }));
    expect(onToggleSpeech).toHaveBeenCalledWith("msg-42", "ver-1002");

    await userEvent.click(screen.getByRole("button", { name: "thumbs-up-message-persisted-msg-42" }));
    expect(onFeedback).toHaveBeenCalledWith("msg-42", "ver-1002", null);

    await userEvent.click(screen.getByRole("button", { name: "thumbs-down-message-persisted-msg-42" }));
    expect(onFeedback).toHaveBeenCalledWith("msg-42", "ver-1002", "down");
  });

  it("disables regenerate after reaching the 3-version limit and shows the limit hint", async () => {
    const onRegenerate = vi.fn();

    const message: ChatMessageItem = {
      id: "persisted-msg-88",
      role: "assistant",
      text: "这是第三个版本。",
      current_version_id: "ver-2003",
      can_regenerate: true,
      meta: { ...emptyMeta },
      versions: [
        {
          id: "ver-2001",
          version_index: 1,
          kind: "original",
          text: "这是原始版本。",
          meta: null,
          feedback: null,
          speech_status: null,
          created_at: "2026-04-07T00:00:00+08:00",
        },
        {
          id: "ver-2002",
          version_index: 2,
          kind: "regenerated",
          text: "这是第二个版本。",
          meta: null,
          feedback: null,
          speech_status: null,
          created_at: "2026-04-07T00:01:00+08:00",
        },
        {
          id: "ver-2003",
          version_index: 3,
          kind: "regenerated",
          text: "这是第三个版本。",
          meta: null,
          feedback: null,
          speech_status: null,
          created_at: "2026-04-07T00:02:00+08:00",
        },
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} onRegenerate={onRegenerate} />);

    const regenerateButton = screen.getByRole("button", { name: "regenerate-message-persisted-msg-88" });
    expect(regenerateButton).toBeDisabled();
    expect(regenerateButton.closest("span")).toHaveAttribute("title", "最多生成三次无法重新生成");
    expect(screen.getByText("3/3")).toBeInTheDocument();

    await userEvent.click(regenerateButton);
    expect(onRegenerate).not.toHaveBeenCalled();
  });

  it("renders tool parts inline and opens the tool detail panel", async () => {
    const message: ChatMessageItem = {
      id: "assistant-steps",
      role: "assistant",
      text: "你好！让我查一下当前位置天气。根据查询结果，今天适合出门。",
      parts: [
        textPart("text-1", "你好！让我查一下当前位置天气。"),
        toolPart("tool-weather", "amap-mcp-server_maps_weather", {
          input: { city: "杭州" },
          output: "杭州晴，26℃",
          status: "success",
          toolCallId: "call-1",
        }),
        toolPart("tool-geocode", "amap-mcp-server_maps_reverse_geocode", {
          input: { lat: 30.27, lng: 120.15 },
          output: "杭州市西湖区",
          status: "success",
          toolCallId: "call-2",
        }),
        textPart("text-2", "根据查询结果，今天适合出门。"),
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.getByText("你好！让我查一下当前位置天气。")).toBeInTheDocument();
    // Consecutive tools are grouped: shows first name + "+1"
    const groupButton = screen.getByRole("button", { name: "open-tool-group-assistant-steps-1" });
    expect(groupButton).toHaveTextContent("高德地图 · 天气查询");
    expect(groupButton).toHaveTextContent("+1");
    expect(screen.getByText("根据查询结果，今天适合出门。")).toBeInTheDocument();

    // Click the group button → opens group list
    await userEvent.click(groupButton);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Click the first tool in the list → opens detail
    const weatherItem = within(dialog).getByText("高德地图 · 天气查询").closest("button");
    await userEvent.click(weatherItem!);

    expect(screen.getByText(/"city": "杭州"/)).toBeInTheDocument();
    expect(screen.getByText("杭州晴，26℃")).toBeInTheDocument();
  });

  it("falls back to a readable label when no chinese mapping exists", async () => {
    const message: ChatMessageItem = {
      id: "assistant-unknown-tool",
      role: "assistant",
      text: "我来继续处理。",
      parts: [toolPart("tool-unknown", "custom_tool_name", { input: { value: 1 }, output: "Completed" })],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // Single tool in group: button shows the fallback name
    const groupButton = screen.getByRole("button", { name: "open-tool-group-assistant-unknown-tool-0" });
    expect(groupButton).toHaveTextContent("custom tool name");

    // Single tool group → click goes directly to detail
    await userEvent.click(groupButton);

    // The dialog title also shows the tool name
    expect(await screen.findAllByText("custom tool name")).toHaveLength(2);
  });

  it("formats object tool payload in the tool detail panel", async () => {
    const message: ChatMessageItem = {
      id: "assistant-exa-tool",
      role: "assistant",
      text: "我先帮你查一下网页资料。",
      parts: [
        toolPart("tool-exa", "exa_web_search_advanced_exa", {
          toolCallId: "call-exa-1",
          input: { query: "京都攻略", num_results: 3 },
          output: {
            kind: "exa_search",
            results: [{ title: "Kyoto Guide", url: "https://example.com/kyoto" }],
          },
        }),
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // Single tool group → click goes directly to detail
    await userEvent.click(screen.getByRole("button", { name: "open-tool-group-assistant-exa-tool-0" }));

    expect(await screen.findByText(/"kind": "exa_search"/)).toBeInTheDocument();
    expect(screen.getByText(/"title": "Kyoto Guide"/)).toBeInTheDocument();
    expect(screen.getByText(/"query": "京都攻略"/)).toBeInTheDocument();
  });

  it("renders reasoning toggle and reveals content after click", async () => {
    const message: ChatMessageItem = {
      id: "assistant-reasoning",
      role: "assistant",
      text: "这是最终答复。",
      parts: [reasoningPart("reasoning-1", "先拆解问题，再整理答复。"), textPart("text-1", "这是最终答复。")],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // 默认折叠：能看到入口标签和最终答复，但思考内容不可见
    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText("这是最终答复。")).toBeInTheDocument();
    expect(screen.queryByText("先拆解问题，再整理答复。")).not.toBeInTheDocument();

    // 点击入口后展开
    await userEvent.click(screen.getByRole("button", { name: "toggle-reasoning-reasoning-1" }));
    expect(screen.getByText("先拆解问题，再整理答复。")).toBeInTheDocument();
  });

  it("shows '思考中' label while reasoning is streaming", () => {
    const message: ChatMessageItem = {
      id: "assistant-reasoning-streaming",
      role: "assistant",
      text: "",
      parts: [reasoningPart("reasoning-1", "正在思考...", "streaming")],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.getByText("思考中")).toBeInTheDocument();
    // 流式态下也保持折叠
    expect(screen.queryByText("正在思考...")).not.toBeInTheDocument();
  });

  it("shows stop icon when current speech is playing", () => {
    const message: ChatMessageItem = {
      id: "persisted-msg-77",
      role: "assistant",
      text: "正在播放的回复。",
      current_version_id: "ver-301",
      meta: { ...emptyMeta },
      versions: [
        {
          id: "ver-301",
          version_index: 1,
          kind: "original",
          text: "正在播放的回复。",
          meta: null,
          feedback: null,
          speech_status: "generating",
          speech_mime_type: "audio/mpeg",
          created_at: "2026-04-07T00:00:00+08:00",
        },
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} isSpeechPlaying={true} />);

    expect(screen.getByRole("button", { name: "stop-speech-message-persisted-msg-77" })).toBeInTheDocument();
  });

  it("renders hotel cards inline when tool output matches hotel schema", () => {
    const hotelOutput = JSON.stringify([
      { name: "如家酒店", price: 299, rating: 4.5, address: "北京朝阳区", star: 3, tags: ["近地铁", "含早"] },
      { name: "汉庭酒店", price: 259, rating: 4.2, address: "北京海淀区", star: 3 },
    ]);

    const message: ChatMessageItem = {
      id: "assistant-hotel",
      role: "assistant",
      text: "我找到了以下酒店推荐：",
      parts: [
        toolPart("tool-hotel-1", "rollinggo-hotel_searchHotels", {
          input: { city: "北京", checkIn: "2026-05-01" },
          output: hotelOutput,
          status: "success",
          toolCallId: "call-hotel-1",
        }),
        textPart("text-1", "我找到了以下酒店推荐："),
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // Hotel cards rendered inline
    expect(screen.getByText("如家酒店")).toBeInTheDocument();
    expect(screen.getByText("汉庭酒店")).toBeInTheDocument();
    expect(screen.getByText("¥299")).toBeInTheDocument();
    expect(screen.getByText("¥259")).toBeInTheDocument();
    expect(screen.getByText("北京朝阳区")).toBeInTheDocument();
    expect(screen.getByText("近地铁")).toBeInTheDocument();
    expect(screen.getByText("含早")).toBeInTheDocument();
    expect(screen.getByText("共 2 家酒店")).toBeInTheDocument();
    // Tool button still clickable for details
    expect(screen.getByRole("button", { name: "open-tool-group-assistant-hotel-0" })).toBeInTheDocument();
  });

  it("does not render hotel cards for non-hotel tools", () => {
    const message: ChatMessageItem = {
      id: "assistant-weather",
      role: "assistant",
      text: "查询完成。",
      parts: [
        toolPart("tool-weather", "amap-mcp-server_maps_weather", {
          input: { city: "杭州" },
          output: JSON.stringify([{ name: "杭州市", price: 0, address: "浙江" }]),
          status: "success",
          toolCallId: "call-w-1",
        }),
        textPart("text-1", "查询完成。"),
      ],
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // Should NOT render hotel cards (tool name doesn't match 'hotel')
    expect(screen.queryByText("共 1 家酒店")).not.toBeInTheDocument();
  });

  it("renders citation chips for text parts with annotations", () => {
    const message: ChatMessageItem = {
      id: "assistant-cite",
      role: "assistant",
      text: "三亚湾希尔顿评分4.8[src-1]，海棠湾万豪也不错[src-2]。",
      parts: [
        {
          id: "text-1",
          type: "text" as const,
          text: "三亚湾希尔顿评分4.8[src-1]，海棠湾万豪也不错[src-2]。",
          status: "completed" as const,
          annotations: [
            {
              type: "citation" as const,
              url: "https://hilton.com/sanya",
              title: "三亚希尔顿",
              start_index: 11,
              end_index: 18,
              cited_text: "[src-1]",
            },
            {
              type: "citation" as const,
              url: "https://marriott.com/haitang",
              title: "海棠湾万豪",
              start_index: 26,
              end_index: 33,
              cited_text: "[src-2]",
            },
          ],
        },
      ],
      meta: { ...emptyMeta },
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    // Citation chips should be rendered as links with correct href
    const chips = screen.getAllByText(/^\[\d+\]$/);
    expect(chips.length).toBe(2);
    expect(chips[0].closest("a")).toHaveAttribute("href", "https://hilton.com/sanya");
    expect(chips[1].closest("a")).toHaveAttribute("href", "https://marriott.com/haitang");
    // Verify chip class for styling
    expect(chips[0].closest("a")).toHaveClass("citation-chip");
  });
});
