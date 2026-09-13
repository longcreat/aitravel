import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useVoiceInput } from "@/features/chat/hooks/use-voice-input";

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

  finishActionSent(): boolean {
    return this.sent.some((item) => item === '{"action":"finish"}');
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static lastOptions: AudioContextOptions | null = null;

  sampleRate = 16000;
  state = "running";
  destination = {};
  close = vi.fn().mockResolvedValue(undefined);
  private processor: {
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    onaudioprocess: ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null;
  } | null = null;

  constructor(options?: AudioContextOptions) {
    FakeAudioContext.lastOptions = options ?? null;
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

interface Harness {
  result: { current: ReturnType<typeof useVoiceInput> };
  started: ReturnType<typeof vi.fn>;
  resolved: ReturnType<typeof vi.fn>;
  failed: ReturnType<typeof vi.fn>;
}

async function pressAndStart(): Promise<Harness> {
  const started = vi.fn();
  const resolved = vi.fn();
  const failed = vi.fn();
  const { result } = renderHook(() =>
    useVoiceInput({ onUtteranceStarted: started, onUtteranceResolved: resolved, onUtteranceFailed: failed }),
  );

  // getUserMedia mock 在微任务中解析；让出两个微任务后音频管线同步完成并置为 recording。
  // 不用 vi.waitFor 轮询 status：与 React act 提交时机存在竞态。
  await act(async () => {
    result.current.press();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => {
    lastSocket().open();
  });
  expect(result.current.status).toBe("recording");
  return { result, started, resolved, failed };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  FakeAudioContext.instances = [];
  FakeAudioContext.lastOptions = null;
  setupBrowserMocks();
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("useVoiceInput", () => {
  it("press() 建连携带 token，管线就绪后进入 recording", async () => {
    const { result } = await pressAndStart();

    expect(lastSocket().url).toContain("/api/stt/ws");
    expect(lastSocket().url).toContain(`token=${encodeURIComponent(TEST_TOKEN)}`);
    expect(result.current.status).toBe("recording");
    // 关键：以 16kHz 创建 AudioContext，交给浏览器做带抗混叠的原生重采样
    expect(FakeAudioContext.lastOptions).toEqual({ sampleRate: 16000 });
  });

  it("多段识别（松手前/后各一段 completed）累积拼接完整文本", async () => {
    const { result, resolved } = await pressAndStart();

    // 录音中：第一段完成（VAD/多段场景），不结算只累积
    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查一下天气。", sentence_end: true }));
    });
    expect(resolved).not.toHaveBeenCalled();

    act(() => {
      result.current.release();
    });

    await act(async () => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "顺便推荐景点。", sentence_end: true }));
    });

    expect(resolved).toHaveBeenCalledTimes(1);
    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我查一下天气。顺便推荐景点。");
  });

  it("建连前的音频帧先暂存，open 后补发", async () => {
    const { result } = renderHook(() =>
      useVoiceInput({ onUtteranceStarted: vi.fn(), onUtteranceResolved: vi.fn(), onUtteranceFailed: vi.fn() }),
    );

    await act(async () => {
      result.current.press();
      await vi.waitFor(() => expect(FakeAudioContext.instances.length).toBe(1));
      // WS 尚未 open 时先产生音频
      FakeAudioContext.instances[0].emitAudio(new Float32Array(1024).fill(0.5));
    });

    expect(lastSocket().sent.filter((item) => item instanceof ArrayBuffer)).toHaveLength(0);

    await act(async () => {
      lastSocket().open();
      await vi.waitFor(() => expect(result.current.status).toBe("recording"));
      FakeAudioContext.instances[0].emitAudio(new Float32Array(1024).fill(0.5));
    });

    const frames = lastSocket().sent.filter((item) => item instanceof ArrayBuffer);
    expect(frames.length).toBeGreaterThanOrEqual(2);
  });

  it("48kHz 采样降采样为 16kHz PCM16", async () => {
    const { result } = await pressAndStart();
    const context = FakeAudioContext.instances[0];
    context.sampleRate = 48000;

    act(() => {
      context.emitAudio(new Float32Array(4096).fill(0.5));
    });

    const frame = lastSocket().sent.find((item) => item instanceof ArrayBuffer) as ArrayBuffer;
    expect(frame.byteLength).toBe(Math.floor(4096 / 3) * 2);
  });

  it("录音中实时更新 interimText；松手后立即复位且后续 interim 不再上屏", async () => {
    const { result, started } = await pressAndStart();

    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "我想去", sentence_end: false }));
    });
    expect(result.current.interimText).toBe("我想去");

    act(() => {
      result.current.release();
    });

    // 松手瞬间：输入条复位，等待气泡挂起
    expect(result.current.status).toBe("idle");
    expect(result.current.interimText).toBe("");
    expect(started).toHaveBeenCalledTimes(1);
    expect(lastSocket().finishActionSent()).toBe(true);

    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "我想去北京", sentence_end: false }));
    });
    expect(result.current.interimText).toBe("");
  });

  it("松手后收到最终句立即结算且不因 done 重复结算", async () => {
    const { result, started, resolved, failed } = await pressAndStart();

    act(() => {
      result.current.release();
    });
    expect(started).toHaveBeenCalledTimes(1);

    await act(async () => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查天气", sentence_end: true }));
    });

    expect(resolved).toHaveBeenCalledTimes(1);
    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我查天气");
    expect(failed).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");

    await act(async () => {
      lastSocket().receive(JSON.stringify({ type: "done", text: "帮我查天气" }));
    });
    expect(resolved).toHaveBeenCalledTimes(1);
  });

  it("松手后收到 done 事件结算完整文本", async () => {
    const { resolved } = await pressAndStart();

    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我", sentence_end: false }));
    });

    await act(async () => {
      lastSocket().receive(JSON.stringify({ type: "done", text: "帮我规划行程" }));
    });

    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我规划行程");
  });

  it("极快点击：松手时建连未完成，open 后自动补发 finish", async () => {
    const { result } = renderHook(() =>
      useVoiceInput({ onUtteranceStarted: vi.fn(), onUtteranceResolved: vi.fn(), onUtteranceFailed: vi.fn() }),
    );

    await act(async () => {
      result.current.press();
      await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
      // 管线未就绪、WS 未 open 时就松手
      result.current.release();
    });

    expect(result.current.status).toBe("idle");
    expect(lastSocket().finishActionSent()).toBe(false);

    await act(async () => {
      lastSocket().open();
      await vi.waitFor(() => expect(lastSocket().finishActionSent()).toBe(true));
    });
  });

  it("上滑取消：直接丢弃会话，不产生任何话语回调", async () => {
    const { result, started, resolved, failed } = await pressAndStart();

    act(() => {
      result.current.cancel();
    });

    expect(result.current.status).toBe("idle");
    expect(lastSocket().readyState).toBe(3);
    expect(started).not.toHaveBeenCalled();
    expect(resolved).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
  });

  it("松手后超时且有部分文本：按部分文本结算", async () => {
    vi.useFakeTimers();
    const { result, resolved, failed } = await pressAndStart();

    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查", sentence_end: false }));
      result.current.release();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
    });

    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我查");
    expect(failed).not.toHaveBeenCalled();
  });

  it("松手后超时且无文本：静默失败", async () => {
    vi.useFakeTimers();
    const { result, resolved, failed } = await pressAndStart();

    act(() => {
      result.current.release();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
    });

    expect(resolved).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledWith(expect.any(String), "语音识别超时，请重试");
  });

  it("录音中断连：输入条内联报错且无话语回调", async () => {
    const { result, started, failed } = await pressAndStart();

    act(() => {
      lastSocket().onclose?.({});
    });

    expect(result.current.status).toBe("idle");
    expect(result.current.error).toContain("断开");
    expect(started).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
  });

  it("松手后断连且有部分文本：按部分文本结算", async () => {
    const { result, resolved } = await pressAndStart();

    act(() => {
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查", sentence_end: false }));
      result.current.release();
      lastSocket().onclose?.({});
    });

    expect(result.current.status).toBe("idle");
    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我查");
  });

  it("松手后服务端报错：话语失败并带错误信息", async () => {
    const { result, failed } = await pressAndStart();

    act(() => {
      result.current.release();
      lastSocket().receive(JSON.stringify({ type: "error", message: "识别服务异常" }));
    });

    expect(result.current.status).toBe("idle");
    expect(failed).toHaveBeenCalledWith(expect.any(String), "识别服务异常");
  });

  it("未登录按住：提示登录且不建连", async () => {
    localStorage.removeItem("ai-travel-access-token");
    const { result } = renderHook(() =>
      useVoiceInput({ onUtteranceStarted: vi.fn(), onUtteranceResolved: vi.fn(), onUtteranceFailed: vi.fn() }),
    );

    act(() => {
      result.current.press();
    });

    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(result.current.error).toContain("登录");
  });

  it("16kHz 采集全零静音流时自动回退默认采样率重建管线", async () => {
    vi.useFakeTimers();
    const { result, resolved, failed } = await pressAndStart();
    const context = FakeAudioContext.instances[0];

    act(() => {
      // 连续送入全零帧，模拟 Chrome 非原生采样率静音 bug
      context.emitAudio(new Float32Array(1024));
      context.emitAudio(new Float32Array(1024));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    // 旧管线被拆掉，用默认采样率重建了第二个 context，会话仍然存活
    expect(FakeAudioContext.instances.length).toBe(2);
    expect(result.current.status).toBe("recording");

    await act(async () => {
      FakeAudioContext.instances[1].emitAudio(new Float32Array(1024).fill(0.5));
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查天气", sentence_end: false }));
      result.current.release();
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "帮我查天气", sentence_end: true }));
    });

    expect(resolved).toHaveBeenCalledWith(expect.any(String), "帮我查天气");
    expect(failed).not.toHaveBeenCalled();
  });

  it("近零抖动静音流（噪声抑制残留）同样触发自愈回退", async () => {
    vi.useFakeTimers();
    const { result } = await pressAndStart();
    const context = FakeAudioContext.instances[0];

    act(() => {
      // 0.0001 远低于健康底噪阈值，但不是纯零 —— 旧的 ===0 判定会漏掉
      context.emitAudio(new Float32Array(1024).fill(0.0001));
      context.emitAudio(new Float32Array(1024).fill(0.0001));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    expect(FakeAudioContext.instances.length).toBe(2);
    expect(result.current.status).toBe("recording");
  });

  it("松手后空转写不再静默吞掉，返回明确提示", async () => {
    const { result, resolved, failed } = await pressAndStart();

    await act(async () => {
      result.current.release();
      // 服务端对纯静音音频返回空 transcript 的最终句
      lastSocket().receive(JSON.stringify({ type: "sentence", text: "", sentence_end: true }));
    });

    expect(result.current.status).toBe("idle");
    expect(resolved).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledWith(expect.any(String), "未识别到内容，请重试");
  });

  it("done 事件为空文本时同样返回明确提示", async () => {
    const { result, resolved, failed } = await pressAndStart();

    await act(async () => {
      result.current.release();
      lastSocket().receive(JSON.stringify({ type: "done", text: "" }));
    });

    expect(result.current.status).toBe("idle");
    expect(resolved).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledWith(expect.any(String), "未识别到内容，请重试");
  });

  it("采集到正常声音时不触发静音回退", async () => {
    vi.useFakeTimers();
    const { result } = await pressAndStart();

    act(() => {
      FakeAudioContext.instances[0].emitAudio(new Float32Array(1024).fill(0.5));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    expect(FakeAudioContext.instances.length).toBe(1);
    expect(result.current.status).toBe("recording");
  });

  it("连说两句：松手后可立即再次 press 建立新会话", async () => {
    const { result, started } = await pressAndStart();

    act(() => {
      result.current.release();
    });
    const firstId = started.mock.calls[0][0];

    await act(async () => {
      result.current.press();
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      lastSocket().open();
    });

    expect(started).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances.length).toBe(2);

    act(() => {
      result.current.release();
    });
    expect(started).toHaveBeenCalledTimes(2);
    expect(started.mock.calls[1][0]).not.toBe(firstId);
  });
});
