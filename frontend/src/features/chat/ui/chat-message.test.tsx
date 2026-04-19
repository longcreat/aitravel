import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatMetaInfo, ChatMessageItem } from "@/features/chat/model/chat.types";
import { ChatMessage } from "@/features/chat/ui/chat-message";
import { AppSurfaceOverlayRootContext } from "@/shared/layouts/app-surface-overlay";

const emptyMeta: ChatMetaInfo = {
  tool_traces: [],
  step_groups: [],
  render_segments: [],
  mcp_connected_servers: [],
  mcp_errors: [],
};

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

  it("renders grouped step entry and opens bottom summary dialog", async () => {
    const message: ChatMessageItem = {
      id: "assistant-steps",
      role: "assistant",
      text: "你好！让我查一下当前位置天气。根据查询结果，今天适合出门。",
      meta: {
        ...emptyMeta,
        step_groups: [
          {
            id: "step-1",
            items: [
              {
                id: "call-1",
                tool_name: "amap mcp server maps weather",
                status: "success",
                summary: "Fetched weather data",
              },
              {
                id: "call-2",
                tool_name: "amap mcp server maps reverse geocode",
                status: "success",
                summary: "Resolved current city",
              },
            ],
          },
        ],
        render_segments: [
          {
            type: "text",
            text: "你好！让我查一下当前位置天气。",
          },
          {
            type: "step",
            step_group_id: "step-1",
          },
          {
            type: "text",
            text: "根据查询结果，今天适合出门。",
          },
        ],
      },
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.getByText("你好！让我查一下当前位置天气。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "open-step-summary-assistant-steps-step-1" })).toHaveTextContent("高德地图 · 天气查询 +1");
    expect(screen.getByText("根据查询结果，今天适合出门。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "open-step-summary-assistant-steps-step-1" }));

    expect(await screen.findByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("高德地图 · 天气查询")).toBeInTheDocument();
    expect(screen.getByText("Fetched weather data")).toBeInTheDocument();
    expect(screen.getByText("高德地图 · 逆地理编码")).toBeInTheDocument();
    expect(screen.getByText("Resolved current city")).toBeInTheDocument();
  });

  it("falls back to a readable label when no chinese mapping exists", async () => {
    const message: ChatMessageItem = {
      id: "assistant-unknown-tool",
      role: "assistant",
      text: "我来继续处理。",
      meta: {
        ...emptyMeta,
        step_groups: [
          {
            id: "step-unknown",
            items: [
              {
                id: "call-unknown",
                tool_name: "custom_tool_name",
                status: "success",
                summary: "Completed",
              },
            ],
          },
        ],
        render_segments: [
          {
            type: "step",
            step_group_id: "step-unknown",
          },
        ],
      },
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.getByRole("button", { name: "open-step-summary-assistant-unknown-tool-step-unknown" })).toHaveTextContent("custom tool name");

    await userEvent.click(screen.getByRole("button", { name: "open-step-summary-assistant-unknown-tool-step-unknown" }));

    expect(await screen.findAllByText("custom tool name")).toHaveLength(2);
  });

  it("renders reasoning panel above the assistant answer", () => {
    const message: ChatMessageItem = {
      id: "assistant-reasoning",
      role: "assistant",
      text: "这是最终答复。",
      meta: {
        ...emptyMeta,
        reasoning_text: "先拆解问题，再整理答复。",
        reasoning_state: "completed",
      },
    };

    renderWithOverlayRoot(<ChatMessage message={message} />);

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("先拆解问题，再整理答复。")).toBeInTheDocument();
    expect(screen.getByText("这是最终答复。")).toBeInTheDocument();
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
});
