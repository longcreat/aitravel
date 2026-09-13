import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useVoiceUtterances } from "@/features/chat/hooks/use-voice-utterances";
import type { SendIntentResult } from "@/features/chat/model/chat.types";

function accepted(): Promise<SendIntentResult> {
  return Promise.resolve({ status: "accepted", message: "x" });
}

type SendMock = ReturnType<typeof vi.fn<(text: string) => Promise<SendIntentResult>>>;

function setup(overrides?: {
  loading?: boolean;
  ready?: boolean;
  sendMessage?: (text: string) => Promise<SendIntentResult>;
  onFailed?: (message: string | null) => void;
}) {
  const sendMessage: SendMock = (overrides?.sendMessage as SendMock) ?? vi.fn(accepted);
  const onFailed = overrides?.onFailed ?? vi.fn();
  const props = {
    threadId: "thread-1",
    loading: overrides?.loading ?? false,
    ready: overrides?.ready ?? true,
    sendMessage: sendMessage as (text: string) => Promise<SendIntentResult>,
    onFailed,
  };
  const { result, rerender } = renderHook((next?: typeof props) => useVoiceUtterances(next ?? props), {
    initialProps: props,
  });
  return { result, rerender, props, sendMessage, onFailed };
}

describe("useVoiceUtterances", () => {
  it("started 挂起气泡；resolved 后空闲时立即串行发送并移除气泡", async () => {
    const { result, sendMessage } = setup();

    act(() => {
      result.current.started("u1");
    });
    expect(result.current.pendingIds).toEqual(["u1"]);
    expect(sendMessage).not.toHaveBeenCalled();

    act(() => {
      result.current.resolved("u1", "帮我查天气");
    });
    // 转写完成但尚未开始发送前，气泡保持
    expect(result.current.pendingIds).toEqual(["u1"]);

    await act(async () => {});
    expect(sendMessage).toHaveBeenCalledWith("帮我查天气");
    expect(result.current.pendingIds).toEqual([]);
  });

  it("agent 忙时不发送，loading 变为 false 后自动 drain", async () => {
    const { result, rerender, props, sendMessage } = setup({ loading: true });

    act(() => {
      result.current.started("u1");
      result.current.resolved("u1", "第一句");
    });
    await act(async () => {});
    expect(sendMessage).not.toHaveBeenCalled();

    rerender({ ...props, loading: false });
    await act(async () => {});

    expect(sendMessage).toHaveBeenCalledWith("第一句");
    expect(result.current.pendingIds).toEqual([]);
  });

  it("多条消息按入队顺序逐条发送", async () => {
    const { result, sendMessage } = setup();

    act(() => {
      result.current.started("u1");
      result.current.started("u2");
      result.current.resolved("u1", "第一句");
      result.current.resolved("u2", "第二句");
    });

    await act(async () => {});

    expect(sendMessage.mock.calls.map((call) => call[0])).toEqual(["第一句", "第二句"]);
    expect(result.current.pendingIds).toEqual([]);
  });

  it("failed 移除气泡并把错误交给提示出口；无错误则静默", async () => {
    const { result, onFailed } = setup();

    act(() => {
      result.current.started("u1");
      result.current.started("u2");
      result.current.failed("u1", "识别服务异常");
      result.current.failed("u2", null);
    });

    expect(result.current.pendingIds).toEqual([]);
    expect(onFailed).toHaveBeenCalledWith("识别服务异常");
    expect(onFailed).toHaveBeenCalledWith(null);
  });

  it("发送被 blocked 时放回队头等待下轮，不丢消息", async () => {
    let attempts = 0;
    const { result, sendMessage } = setup({
      sendMessage: vi.fn(async (): Promise<SendIntentResult> => {
        attempts += 1;
        if (attempts === 1) {
          return { status: "blocked", reason: "loading" };
        }
        return { status: "accepted", message: "x" };
      }),
    });

    act(() => {
      result.current.started("u1");
      result.current.resolved("u1", "别丢了我");
    });

    await act(async () => {});
    await act(async () => {});

    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(result.current.pendingIds).toEqual([]);
  });

  it("切换会话时清空队列与气泡", async () => {
    const { result, rerender, props, sendMessage } = setup({ loading: true });

    act(() => {
      result.current.started("u1");
      result.current.resolved("u1", "还没发出去");
    });
    await act(async () => {});
    expect(sendMessage).not.toHaveBeenCalled();

    // 切换会话：未发送的语音消息与气泡一并丢弃
    rerender({ ...props, threadId: "thread-2" });
    await act(async () => {});
    expect(result.current.pendingIds).toEqual([]);

    // 回到空闲后，旧会话的消息也不会再发出去
    rerender({ ...props, threadId: "thread-2", loading: false });
    await act(async () => {});
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
