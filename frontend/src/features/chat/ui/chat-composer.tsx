import { ArrowUp, Keyboard, Mic, Square } from "lucide-react";
import { FormEvent, useState, useRef, useEffect } from "react";

import type { SendIntentResult } from "@/features/chat/model/chat.types";
import { Button } from "@/shared/ui";

interface ChatComposerProps {
  loading: boolean;
  ready: boolean;
  onSend: (message: string) => Promise<SendIntentResult>;
  onStop: () => void;
}

export function ChatComposer({ loading, ready, onSend, onStop }: ChatComposerProps) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"text" | "voice">("text");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  return (
    <form
      className="relative bottom-0 z-10 px-4 pb-4 pt-10 bg-gradient-to-t from-paper via-paper to-transparent"
      onSubmit={handleSubmit}
    >
      <div className="mx-auto max-w-3xl">
        {mode === "text" ? (
          <div className="group flex min-h-[52px] items-center gap-2 rounded-xl bg-white px-4 py-3 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06),0_2px_8px_-2px_rgba(0,0,0,0.03)] transition-all focus-within:shadow-[0_8px_32px_-8px_rgba(0,0,0,0.10)]">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="发消息或按住说话"
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
                onClick={() => setMode("voice")}
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
          <div className="fade-up flex min-h-[52px] items-center gap-2 rounded-xl bg-white px-4 shadow-[0_4px_24px_-4px_rgba(0,0,0,0.06),0_2px_8px_-2px_rgba(0,0,0,0.03)] transition-all">
            <div className="flex flex-1 items-center justify-center gap-2 text-muted-foreground">
              <span className="text-base select-none">按住 说话</span>
            </div>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={() => setMode("text")}
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
