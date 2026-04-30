import type { ComponentPropsWithoutRef } from "react";
import { useEffect, useRef, useState } from "react";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  LoaderCircle,
  Play,
  RefreshCcw,
  Square,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "br", "sub", "sup", "mark", "del", "ins"],
};

import { getToolDisplayName } from "@/features/chat/model/tool-display-name";
import type { ChatMessageItem } from "@/features/chat/model/chat.types";
import { useBrowser } from "@/shared/lib/browser";
import { cn } from "@/shared/lib/cn";
import { AppSurfaceSheet } from "@/shared/ui";

interface ChatMessageProps {
  message: ChatMessageItem;
  onRegenerate?: (messageId: string) => Promise<void> | void;
  onSwitchVersion?: (messageId: string, versionId: string) => Promise<void> | void;
  onFeedback?: (messageId: string, versionId: string, feedback: "up" | "down" | null) => Promise<void> | void;
  onToggleSpeech?: (messageId: string, versionId: string) => Promise<void> | void;
  isSpeechPlaying?: boolean;
}

const MAX_ASSISTANT_VERSIONS = 3;
const REGENERATE_LIMIT_MESSAGE = "最多生成三次无法重新生成";

async function copyPlainText(text: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  if (typeof document === "undefined") {
    throw new Error("clipboard-unavailable");
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function MarkdownBubble({
  content,
  isUser,
}: {
  content: string;
  isUser: boolean;
}) {
  const { openUrl } = useBrowser();

  return (
    <div className="max-w-none space-y-4 break-words text-base leading-[1.8] tracking-[0.01em] [line-break:auto] [text-wrap:pretty] [&_*]:break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
        components={{
          p: ({ children }) => <p className="text-base leading-[1.8] [text-wrap:pretty]">{children}</p>,
          h1: ({ children }) => <h1 className="text-2xl font-bold leading-tight">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xl font-semibold leading-tight">{children}</h2>,
          h3: ({ children }) => <h3 className="text-lg font-semibold leading-tight">{children}</h3>,
          ul: ({ children }) => <ul className="list-disc pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5">{children}</ol>,
          li: ({ children }) => <li className="leading-[1.8]">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote
              className={cn(
                "rounded-[8px] border-l-4 px-3 py-2 italic",
                isUser ? "border-[#90b9df] bg-[#dceefe]" : "border-[#cfd9dc] bg-[#f6f8f8]",
              )}
            >
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              className={cn("font-medium underline underline-offset-2", isUser ? "text-[#0c5577]" : "text-[#177199]")}
              onClick={(e) => {
                if (href && /^https?:\/\//i.test(href)) {
                  e.preventDefault();
                  openUrl(href);
                }
              }}
            >
              {children}
            </a>
          ),
          hr: () => <div className={cn("my-3 h-px", isUser ? "bg-[#b7d6f1]" : "bg-[#e5eded]")} />,
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse overflow-hidden rounded-[8px] text-left text-[13px]">{children}</table>
            </div>
          ),
          strong: ({ children }) => <strong className="font-bold text-[#d4704e]">{children}</strong>,
          thead: ({ children }) => (
            <thead className={cn(isUser ? "bg-[#d8ebfb]" : "bg-[#f4f7f7]")}>{children}</thead>
          ),
          th: ({ children }) => <th className="border border-[#dfe8ea] px-3 py-2 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-[#dfe8ea] px-3 py-2 align-top">{children}</td>,
          code: ({ inline, className, children, ...props }: ComponentPropsWithoutRef<"code"> & { inline?: boolean }) => {
            if (inline) {
              return (
                <code
                  {...props}
                  className={cn(
                    "rounded-[6px] px-1.5 py-0.5 font-mono text-[0.9em]",
                    isUser ? "bg-[#d2e8fa] text-[#12394a]" : "bg-[#f2f5f5] text-[#21484f]",
                    className,
                  )}
                >
                  {children}
                </code>
              );
            }

            return (
              <code
                {...props}
                className={cn(
                  "block overflow-x-auto rounded-[8px] px-3 py-3 font-mono text-[13px] leading-6",
                  isUser ? "bg-[#d2e8fa] text-[#12394a]" : "bg-[#f4f7f8] text-[#15363b]",
                  className,
                )}
              >
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="overflow-x-auto">{children}</pre>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ReasoningPanel({
  content,
  state,
}: {
  content: string;
  state: "streaming" | "completed" | null;
}) {
  return (
    <div className="mb-4 rounded-[12px] border border-[#efe4d3] bg-[#fbf6eb] px-3 py-3">
      <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.12em] text-[#b07a4d]">
        <span>思考过程</span>
        <span>{state === "streaming" ? "思考中" : "已完成"}</span>
      </div>
      <div className="whitespace-pre-wrap break-words text-[14px] leading-6 text-[#6f6557]">{content}</div>
    </div>
  );
}

export function ChatMessage({
  message,
  onRegenerate,
  onSwitchVersion,
  onFeedback,
  onToggleSpeech,
  isSpeechPlaying = false,
}: ChatMessageProps) {
  const isUser = message.role === "user";
  const messageParts = !isUser ? message.parts ?? [] : [];
  const reasoningParts = !isUser
    ? messageParts.filter((part): part is Extract<(typeof messageParts)[number], { type: "reasoning" }> => part.type === "reasoning")
    : [];
  const reasoningText = reasoningParts.map((part) => part.text).join("").trim();
  const reasoningState = reasoningParts.some((part) => part.status === "streaming") ? "streaming" : reasoningParts.length ? "completed" : null;
  const shouldShowTypingOnly = !isUser && !message.text && messageParts.length === 0;
  const [copied, setCopied] = useState(false);
  const [activeToolGroupIndex, setActiveToolGroupIndex] = useState<number | null>(null);
  const copiedTimeoutRef = useRef<number | null>(null);
  const persistedMessageId = message.id.startsWith("persisted-")
    ? message.id.slice("persisted-".length)
    : null;
  const versions = message.versions ?? [];
  const currentVersion =
    versions.find((item) => item.id === message.current_version_id) ??
    versions[versions.length - 1] ??
    null;
  const currentFeedback = currentVersion?.feedback ?? null;
  const canShowCopy = !isUser && Boolean(message.text) && message.status !== "streaming";
  const canShowPersistedActions = canShowCopy && persistedMessageId != null;
  const canShowFeedback = canShowPersistedActions && currentVersion != null;
  const canShowSpeech =
    canShowPersistedActions &&
    currentVersion != null &&
    (currentVersion.speech_status === "generating" || currentVersion.speech_status === "ready");
  const canShowRegenerate = canShowFeedback && Boolean(message.can_regenerate);
  const regenerateLimitReached = versions.length >= MAX_ASSISTANT_VERSIONS;
  const canRegenerate = canShowRegenerate && !regenerateLimitReached;
  const canSwitchVersions = canRegenerate && versions.length > 1;
  // Group consecutive tool parts for collapsed display
  type ToolPart = Extract<(typeof messageParts)[number], { type: "tool" }>;
  type PartGroup = { kind: "text" | "reasoning" | "tools"; parts: typeof messageParts };
  const partGroups: PartGroup[] = [];
  for (const part of messageParts) {
    if (part.type === "tool") {
      const last = partGroups[partGroups.length - 1];
      if (last && last.kind === "tools") {
        last.parts.push(part);
      } else {
        partGroups.push({ kind: "tools", parts: [part] });
      }
    } else {
      partGroups.push({ kind: part.type, parts: [part] });
    }
  }
  const activeToolGroup =
    activeToolGroupIndex != null ? (partGroups[activeToolGroupIndex]?.parts as ToolPart[] | undefined) ?? null : null;
  const [activeToolDetailId, setActiveToolDetailId] = useState<string | null>(null);
  const activeToolDetail = activeToolGroup?.find((p) => p.id === activeToolDetailId) ?? null;

  function formatPayload(payload: unknown): string {
    if (payload === null || payload === undefined) return "(空)";
    if (typeof payload === "string") {
      try {
        return JSON.stringify(JSON.parse(payload), null, 2);
      } catch {
        return payload;
      }
    }
    try {
      return JSON.stringify(payload, null, 2);
    } catch {
      return String(payload);
    }
  }

  useEffect(() => {
    return () => {
      if (copiedTimeoutRef.current != null) {
        window.clearTimeout(copiedTimeoutRef.current);
      }
    };
  }, []);

  async function handleCopyMessage() {
    if (!message.text) {
      return;
    }

    await copyPlainText(message.text);
    setCopied(true);
    if (copiedTimeoutRef.current != null) {
      window.clearTimeout(copiedTimeoutRef.current);
    }
    copiedTimeoutRef.current = window.setTimeout(() => {
      setCopied(false);
      copiedTimeoutRef.current = null;
    }, 1800);
  }

  async function handleFeedback(nextFeedback: "up" | "down") {
    if (persistedMessageId == null || !currentVersion || !onFeedback) {
      return;
    }
    await onFeedback(
      persistedMessageId,
      currentVersion.id,
      currentFeedback === nextFeedback ? null : nextFeedback,
    );
  }

  function renderAssistantBody() {
    if (!messageParts.length) {
      if (message.text) {
        return <MarkdownBubble content={message.text} isUser={false} />;
      }
      return (
        <div className="flex items-center gap-1.5 px-1 py-1">
          <span className="typing-dot" style={{ animationDelay: "0ms" }} />
          <span className="typing-dot" style={{ animationDelay: "160ms" }} />
          <span className="typing-dot" style={{ animationDelay: "320ms" }} />
        </div>
      );
    }

    return (
      <div className="space-y-1">
        {partGroups.map((group, groupIdx) => {
          if (group.kind === "reasoning") {
            return null;
          }
          if (group.kind === "text") {
            const textPart = group.parts[0] as Extract<(typeof messageParts)[number], { type: "text" }>;
            return <MarkdownBubble key={textPart.id} content={textPart.text} isUser={false} />;
          }
          // Tool group
          const toolParts = group.parts as ToolPart[];
          const firstTool = toolParts[0];
          const extraCount = toolParts.length - 1;
          const hasRunning = toolParts.some((p) => p.status === "running");
          const hasError = toolParts.some((p) => p.status === "error");
          return (
            <button
              key={firstTool.id}
              type="button"
              aria-label={`open-tool-group-${message.id}-${groupIdx}`}
              className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[14px] font-medium text-[#7a766d] transition-colors hover:bg-[#f0ece4]"
              onClick={() => {
                setActiveToolGroupIndex(groupIdx);
                if (toolParts.length === 1) setActiveToolDetailId(firstTool.id);
              }}
            >
              {hasRunning ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : hasError ? (
                <AlertTriangle className="h-4 w-4 text-[#bf5f4b]" />
              ) : (
                <CheckCircle2 className="h-4 w-4 text-[#6d8a6f]" />
              )}
              <span>{getToolDisplayName(firstTool.tool_name)}</span>
              {extraCount > 0 && (
                <span className="rounded-full bg-[#f0ece4] px-1.5 py-0.5 text-[11px] font-semibold text-[#8a857b]">+{extraCount}</span>
              )}
              <ChevronRight className="h-4 w-4 opacity-50" />
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className={cn("fade-up flex", isUser ? "px-4" : "px-3")}>
      <div className={cn("flex w-full flex-col", isUser ? "items-end" : "items-start")}>
        {shouldShowTypingOnly ? (
          <div className="flex items-center gap-1.5 px-2 py-1">
            <span className="typing-dot" style={{ animationDelay: "0ms" }} />
            <span className="typing-dot" style={{ animationDelay: "160ms" }} />
            <span className="typing-dot" style={{ animationDelay: "320ms" }} />
          </div>
        ) : (
          <div
            className={cn(
              "rounded-xl border text-base leading-relaxed break-words",
              isUser
                ? "max-w-[90%] border-[#e8d5c4] bg-[#f5ede4] px-5 py-2.5 text-[#2c2b28] shadow-sm"
                : "w-full border-[#2c2b28]/[0.06] bg-white px-4 py-4 text-[#2c2b28] shadow-sm",
            )}
          >
            {!isUser && reasoningText ? <ReasoningPanel content={reasoningText} state={reasoningState} /> : null}
            {isUser ? <MarkdownBubble content={message.text} isUser={true} /> : renderAssistantBody()}
          </div>
        )}
        {canShowCopy ? (
          <div className="mt-2 flex items-center gap-1.5">
            <button
              type="button"
              aria-label={`copy-message-${message.id}`}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-[#6f8589] transition-colors hover:bg-[#eef4f4] hover:text-[#47686d]"
              onClick={() => void handleCopyMessage()}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>

            {canShowSpeech ? (
              <button
                type="button"
                aria-label={`${isSpeechPlaying ? "stop" : "play"}-speech-message-${message.id}`}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-[#6f8589] transition-colors hover:bg-[#eef4f4] hover:text-[#47686d]"
                onClick={() => persistedMessageId != null && currentVersion && void onToggleSpeech?.(persistedMessageId, currentVersion.id)}
              >
                {isSpeechPlaying ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </button>
            ) : null}

            {canShowRegenerate ? (
              <span title={regenerateLimitReached ? REGENERATE_LIMIT_MESSAGE : undefined}>
                <button
                  type="button"
                  aria-label={`regenerate-message-${message.id}`}
                  disabled={regenerateLimitReached}
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-full transition-colors",
                    regenerateLimitReached
                      ? "cursor-not-allowed bg-[#f6f6f3] text-[#b7b4ad]"
                      : "text-[#6f8589] hover:bg-[#eef4f4] hover:text-[#47686d]",
                  )}
                  onClick={() => persistedMessageId != null && onRegenerate?.(persistedMessageId)}
                >
                  <RefreshCcw className="h-4 w-4" />
                </button>
              </span>
            ) : null}

            {canShowFeedback ? (
              <>
                <button
                  type="button"
                  aria-label={`thumbs-up-message-${message.id}`}
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-full transition-colors",
                    currentFeedback === "up"
                      ? "bg-[#edf7f4] text-[#2a8b6f]"
                      : "text-[#6f8589] hover:bg-[#eef4f4] hover:text-[#47686d]",
                  )}
                  onClick={() => void handleFeedback("up")}
                >
                  <ThumbsUp className="h-4 w-4" />
                </button>

                <button
                  type="button"
                  aria-label={`thumbs-down-message-${message.id}`}
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-full transition-colors",
                    currentFeedback === "down"
                      ? "bg-[#fff1ee] text-[#b95a46]"
                      : "text-[#6f8589] hover:bg-[#eef4f4] hover:text-[#47686d]",
                  )}
                  onClick={() => void handleFeedback("down")}
                >
                  <ThumbsDown className="h-4 w-4" />
                </button>
              </>
            ) : null}

            {versions.length > 1 && canShowRegenerate ? (
              <div className="ml-1 inline-flex items-center gap-1 rounded-full border border-black/[0.06] bg-white px-1 py-0.5">
                <button
                  type="button"
                  aria-label={`previous-version-${message.id}`}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[#6f8589] transition-colors hover:bg-[#eef4f4] hover:text-[#47686d]"
                  onClick={() => {
                    if (persistedMessageId == null || !currentVersion || !onSwitchVersion) {
                      return;
                    }
                    const currentIndex = versions.findIndex((item) => item.id === currentVersion.id);
                    const previous = currentIndex > 0 ? versions[currentIndex - 1] : versions[versions.length - 1];
                    void onSwitchVersion(persistedMessageId, previous.id);
                  }}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[28px] text-center text-[11px] font-semibold text-[#607274]">
                  {currentVersion?.version_index ?? 1}/{versions.length}
                </span>
                <button
                  type="button"
                  aria-label={`next-version-${message.id}`}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[#6f8589] transition-colors hover:bg-[#eef4f4] hover:text-[#47686d]"
                  onClick={() => {
                    if (persistedMessageId == null || !currentVersion || !onSwitchVersion) {
                      return;
                    }
                    const currentIndex = versions.findIndex((item) => item.id === currentVersion.id);
                    const next = currentIndex >= 0 && currentIndex < versions.length - 1 ? versions[currentIndex + 1] : versions[0];
                    void onSwitchVersion(persistedMessageId, next.id);
                  }}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {!isUser && activeToolGroup ? (
          <AppSurfaceSheet
            open={true}
            onClose={() => { setActiveToolGroupIndex(null); setActiveToolDetailId(null); }}
            title={activeToolDetail ? getToolDisplayName(activeToolDetail.tool_name) : "工具调用"}
            closeLabel="close-tool-group"
          >
            <div className="max-h-[60vh] space-y-2 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
              {activeToolDetail ? (
                <>
                  {activeToolGroup.length > 1 && (
                    <button
                      type="button"
                      className="mb-2 inline-flex items-center gap-1 text-[13px] font-medium text-[#7a766d] hover:text-[#2c2b28]"
                      onClick={() => setActiveToolDetailId(null)}
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                      <span>返回列表</span>
                    </button>
                  )}
                  <div className="rounded-[12px] bg-[#faf8f3] px-3 py-3">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8a857b]">入参</div>
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[13px] leading-6 text-[#2c2b28]">
                      {formatPayload(activeToolDetail.input)}
                    </pre>
                  </div>
                  <div className="rounded-[12px] bg-[#faf8f3] px-3 py-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8a857b]">返回结果</span>
                      {activeToolDetail.status === "error" ? (
                        <span className="rounded-full bg-[#fdecea] px-2 py-0.5 text-[11px] font-semibold text-[#bf5f4b]">错误</span>
                      ) : activeToolDetail.status === "success" ? (
                        <span className="rounded-full bg-[#edf7f4] px-2 py-0.5 text-[11px] font-semibold text-[#6d8a6f]">成功</span>
                      ) : null}
                    </div>
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[13px] leading-6 text-[#2c2b28]">
                      {activeToolDetail.status === "running" ? "(执行中...)" : formatPayload(activeToolDetail.output)}
                    </pre>
                  </div>
                </>
              ) : (
                activeToolGroup.map((toolPart) => (
                  <button
                    key={toolPart.id}
                    type="button"
                    className="flex w-full items-center gap-2 rounded-[10px] px-3 py-2.5 text-left transition-colors hover:bg-[#f6f3ee]"
                    onClick={() => setActiveToolDetailId(toolPart.id)}
                  >
                    {toolPart.status === "running" ? (
                      <LoaderCircle className="h-4 w-4 flex-shrink-0 animate-spin text-[#7a766d]" />
                    ) : toolPart.status === "error" ? (
                      <AlertTriangle className="h-4 w-4 flex-shrink-0 text-[#bf5f4b]" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-[#6d8a6f]" />
                    )}
                    <span className="flex-1 text-[14px] font-medium text-[#2c2b28]">{getToolDisplayName(toolPart.tool_name)}</span>
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-[#7a766d] opacity-50" />
                  </button>
                ))
              )}
            </div>
          </AppSurfaceSheet>
        ) : null}
      </div>
    </div>
  );
}
