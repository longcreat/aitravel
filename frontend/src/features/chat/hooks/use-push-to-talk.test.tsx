import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePushToTalk } from "@/features/chat/hooks/use-push-to-talk";

const TEST_TOKEN = "test-token-123";

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = 0;
  sent: Array<ArrayBuffer | string> = [];
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: ArrayBuffer | string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.({});
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  receive(data: unknown): void {
    this.onmessage?.({ data });
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];

  sampleRate = 16000;
  state = "running";
  destination = {};
  close = vi.fn().mockResolvedValue(undefined);
  private processor: {
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null;
  } | null = null;

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  createMediaStreamSource(_stream: MediaStream): { connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> } {
    return { connect: vi.fn(), disconnect: vi.fn() };
  }

  createScriptProcessor(): {
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null;
  } {
    this.processor = { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null };
    return this.processor;
  }

  emitAudio(samples: Float32Array): void {
    this.processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => samples } });
  }
}

function setupBrowserMocks() {
  localStorage.setItem("ai-travel-access-token", TEST_TOKEN);
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }),
    },
    configurable: true,
  });
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("WebSocket", FakeWebSocket);
}

function lastSocket(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1] as FakeWebSocket;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  FakeAudioContext.instances = [];
  setupBrowserMocks();
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("usePushToTalk", () => {
  it("start() 连接 WS 并携带登录 token", async () => {
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal: vi.fn(), onError: vi.fn() }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      lastSocket().open();
    });

    expect(lastSocket().url).toContain("/api/stt/ws");
    expect(lastSocket().url).toContain(`token=${encodeURIComponent(TEST_TOKEN)}`);
    expect(result.current.recording).toBe(true);
  });

  it("未登录时直接报错且不建立连接", async () => {
    localStorage.removeItem("ai-travel-access-token");
    const onError = vi.fn();
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal: vi.fn(), onError }));

    act(() => {
      result.current.start();
    });

    expect(FakeWebSocket.instances.length).toBe(0);
    expect(result.current.error).toContain("登录");
    expect(onError).toHaveBeenCalled();
  });

  it("麦克风被拒时报错", async () => {
    const onError = vi.fn();
    const getUserMedia = navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;
    getUserMedia.mockRejectedValueOnce(new Error("denied"));
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal: vi.fn(), onError }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    });

    await act(async () => {
      await vi.waitFor(() => expect(result.current.error).not.toBeNull());
    });

    expect(result.current.error).toContain("麦克风");
    expect(onError).toHaveBeenCalled();
  });

  it("录音期间音频帧以 PCM16 发送", async () => {
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal: vi.fn(), onError: vi.fn() }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      lastSocket().open();
    });

    const audio = new Float32Array(4096).fill(0.5);
    act(() => {
      FakeAudioContext.instances[0].emitAudio(audio);
    });

    const frame = lastSocket().sent.find((item) => item instanceof ArrayBuffer) as ArrayBuffer | undefined;
    expect(frame).toBeInstanceOf(ArrayBuffer);
    expect(frame?.byteLength).toBe(4096 * 2);
  });

  it("收到中间结果时更新 interimText", async () => {
    const onInterim = vi.fn();
    const { result } = renderHook(() => usePushToTalk({ onInterim, onFinal: vi.fn(), onError: vi.fn() }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      lastSocket().open();
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "我想去", sentence_end: false }));
    });

    expect(result.current.interimText).toBe("我想去");
    expect(onInterim).toHaveBeenCalledWith("我想去");
  });

  it("finish() 后收到 done 事件调用 onFinal 并关闭连接", async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal, onError: vi.fn() }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      lastSocket().open();
    });

    act(() => {
      result.current.finish();
    });
    expect(lastSocket().sent.some((item) => item === '{"action":"finish"}')).toBe(true);

    await act(async () => {
      lastSocket().receive(JSON.stringify({ type: "done", text: "我想去北京" }));
    });

    expect(onFinal).toHaveBeenCalledWith("我想去北京");
    expect(result.current.recording).toBe(false);
    expect(result.current.interimText).toBe("");
  });

  it("cancel() 直接关闭连接不发送结果", async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() => usePushToTalk({ onInterim: vi.fn(), onFinal, onError: vi.fn() }));

    await act(async () => {
      result.current.start();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      lastSocket().open();
    });

    act(() => {
      result.current.cancel();
    });

    expect(lastSocket().readyState).toBe(3);
    expect(onFinal).not.toHaveBeenCalled();
    expect(result.current.recording).toBe(false);
  });
});
