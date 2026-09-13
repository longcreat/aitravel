import { ArrowUp, Brain, ChevronDown, Keyboard, Mic, Square } from "lucide-react";
import { FormEvent, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import type { SendIntentResult } from "@/features/chat/model/chat.types";
import type { VoiceInput } from "@/features/chat/hooks/use-voice-input";
import { Button } from "@/shared/ui";

/** 手指上滑超出输入条顶部该距离后，松手即取消 */
const SLIDE_CANCEL_THRESHOLD_PX = 12;

interface ChatComposerProps {
  loading: boolean;
  ready: boolean;
  modelProfileLabel: string;
  placeholder?: string;
  voice: VoiceInput;
  onSend: (message: string) => Promise<SendIntentResult>;
  onOpenModelProfileSheet: () => void;
  onStop: () => void;
}

/** 录音态均衡器竖条：4 根错相位跳动（纯 CSS 动画） */
function EqualizerBars() {
  return (
    <span className="flex items-center gap-[3px]" aria-hidden="true">
      {[0, 120, 240, 360].map((delay) => (
        <span key={delay} className="voice-eq-bar" style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  );
}

export function ChatComposer({
  loading,
  ready,
  modelProfileLabel,
  placeholder = "发消息或按住说话",
  voice,
  onSend,
  onOpenModelProfileSheet,
  onStop,
}: ChatComposerProps) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [cancelArmed, setCancelArmed] = useState(false);
  const cancelArmedRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const setArmed = (next: boolean) => {
    cancelArmedRef.current = next;
    setCancelArmed(next);
  };

  useEffect(() => {
    if (value === "" && textareaRef.current) {
      textareaRef.current.style.height = "24px";
      textareaRef.current.style.overflowY = "hidden";
    }
  }, [value]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const text = value.trim();
    if (!text || loading || !ready) {
      return;
    }

    const result = await onSend(text);
    if (result.status === "accepted") {
      setValue("");
    }
  }

  function switchToVoice() {
    setMode("voice");
  }

  function switchToText() {
    if (voice.status !== "idle") {
      voice.cancel();
    }
    setMode("text");
  }

  function handleVoicePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // 某些老旧环境不支持 setPointerCapture
    }
    setArmed(false);
    voice.press();
  }

  function handleVoicePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    if (voice.status !== "recording" && voice.status !== "starting") {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const above = event.clientY < rect.top - SLIDE_CANCEL_THRESHOLD_PX;
    if (cancelArmedRef.current !== above) {
      setArmed(above);
    }
  }

  function handleVoicePointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    } catch {
      // 忽略捕获释放错误
    }
    if (cancelArmedRef.current) {
      voice.cancel();
    } else {
      voice.release();
    }
    setArmed(false);
  }

  function handleVoicePointerCancel(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    voice.cancel();
    setArmed(false);
  }

  // starting 与 recording 视觉合并：按下即进入录音态，建连过程（<300ms）对用户无感
  const voiceActive = voice.status === "recording" || voice.status === "starting";
  const voiceCancelHint = voiceActive && cancelArmed;

  return (
    <form
      className="relative bottom-0 z-10 px-4 pb-4 pt-2 bg-gradient-to-t from-paper via-paper to-transparent"
      onSubmit={handleSubmit}
    >
      <div className="mx-auto max-w-3xl">
        <div className="mb-1.5 flex justify-start">
          <button
            type="button"
            aria-label="model-profile-selector"
            className="inline-flex items-center gap-1 rounded-full border border-black/[0.06] bg-white/90 px-3 py-1 text-[12px] font-medium text-[#6b6861] shadow-sm transition-colors hover:bg-white"
            onClick={onOpenModelProfileSheet}
          >
            <Brain className="h-3.5 w-3.5 text-mint" />
            <span>{modelProfileLabel}</span>
            <ChevronDown className="h-3.5 w-3.5 opacity-60" />
          </button>
        </div>

        {mode === "text" ? (
          <div className="group flex min-h-[52px] items-center gap-2 rounded-xl bg-white px-4 py-3 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06),0_2px_8px_-2px_rgba(0,0,0,0.03)] transition-all focus-within:shadow-[0_8px_32px_-8px_rgba(0,0,0,0.10)]">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={placeholder}
              rows={1}
              style={{ height: "24px" }}
              className="flex-1 max-h-32 resize-none border-none bg-transparent py-0 text-base leading-6 text-ink outline-none focus:ring-0 overflow-y-hidden scrollbar-hidden"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.shiftKey) {
                  e.preventDefault();
                  const text = value.trim();
                  if (text && !loading && ready) {
                    void onSend(text).then((result) => {
                      if (result.status === "accepted") {
                        setValue("");
                      }
                    });
                  }
                }
              }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "24px";
                target.style.height = `${target.scrollHeight}px`;
                target.style.overflowY = target.scrollHeight > 128 ? "auto" : "hidden";
              }}
            />
            <div className="flex items-center gap-1 shrink-0">
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={switchToVoice}
                className="h-9 w-9 text-muted-foreground hover:bg-muted hover:text-ink transition-all rounded-full active:scale-90"
                aria-label="switch-to-voice"
              >
                <Mic className="h-5 w-5" />
              </Button>
              {loading ? (
                <Button
                  type="button"
                  size="icon"
                  aria-label="stop-generating"
                  className="h-9 w-9 bg-ink text-white hover:bg-ink/90 transition-all active:scale-95 rounded-full"
                  onClick={onStop}
                >
                  <Square className="h-4 w-4 fill-current" />
                </Button>
              ) : (
                value.trim() && (
                  <Button
                    type="submit"
                    size="icon"
                    aria-label="send-message"
                    disabled={!ready}
                    className="h-9 w-9 bg-ink text-white hover:bg-ink/90 transition-all active:scale-95 rounded-full"
                  >
                    <ArrowUp className="h-5 w-5" />
                  </Button>
                )
              )}
            </div>
          </div>
        ) : (
          <div className="fade-up flex min-h-[52px] items-center gap-2 rounded-xl bg-white px-2 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06),0_2px_8px_-2px_rgba(0,0,0,0.03)] transition-all">
            <button
              type="button"
              aria-label="push-to-talk"
              disabled={!ready}
              onContextMenu={(e) => e.preventDefault()}
              onPointerDown={handleVoicePointerDown}
              onPointerMove={handleVoicePointerMove}
              onPointerUp={handleVoicePointerUp}
              onPointerCancel={handleVoicePointerCancel}
              className={`flex flex-1 min-h-[44px] items-center justify-center gap-2 rounded-lg border px-4 font-medium transition-colors duration-150 select-none touch-none ${
                voiceCancelHint
                  ? "bg-[#fff1ee] border-[#f3d8d0] text-[#b95a46]"
                  : voiceActive
                    ? "bg-[#f5ede4] border-[#e8d5c4] text-ink shadow-sm"
                    : "bg-muted/50 border-transparent text-ink hover:bg-muted active:scale-[0.99]"
              } disabled:opacity-40`}
            >
              {voiceActive && !voiceCancelHint ? (
                <span className="text-mint">
                  <EqualizerBars />
                </span>
              ) : (
                <Mic className="h-4 w-4" />
              )}
              <span className="text-base select-none">
                {voiceActive ? (
                  voiceCancelHint ? (
                    <span className="flex items-center justify-center gap-1.5">
                      <ArrowUp className="h-4 w-4" />
                      松开取消
                    </span>
                  ) : (
                    "松开发送"
                  )
                ) : voice.error ? (
                  <span className="text-xs text-rose-500" role="alert">
                    {voice.error}
                  </span>
                ) : (
                  "按住 说话"
                )}
              </span>
            </button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={switchToText}
              className="h-9 w-9 text-muted-foreground hover:bg-muted hover:text-ink transition-all shrink-0 rounded-full active:scale-90"
              aria-label="switch-to-keyboard"
            >
              <Keyboard className="h-5 w-5" />
            </Button>
          </div>
        )}
      </div>
    </form>
  );
}
