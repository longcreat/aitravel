import type { ComponentPropsWithoutRef } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessageItem } from "@/features/chat/model/chat.types";
import { ItineraryCard } from "@/features/itinerary/ui/itinerary-card";
import { Badge } from "@/shared/ui/badge";
import { cn } from "@/shared/lib/cn";

interface ChatMessageProps {
  message: ChatMessageItem;
}

function MarkdownBubble({
  content,
  isUser,
}: {
  content: string;
  isUser: boolean;
}) {
  const proseClassName = cn(
    "markdown-body max-w-none break-words text-sm leading-7 [overflow-wrap:anywhere] [&_*]:break-words [&_*]:[overflow-wrap:anywhere]",
    isUser ? "markdown-user" : "markdown-assistant",
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
        h1: ({ children }) => <h1 className="mb-3 text-[1.25rem] font-semibold leading-tight last:mb-0">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-3 text-[1.1rem] font-semibold leading-tight last:mb-0">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-2 text-base font-semibold leading-tight last:mb-0">{children}</h3>,
        ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
        li: ({ children }) => <li className="leading-7">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote
            className={cn(
              "mb-3 rounded-[8px] border-l-4 px-3 py-2 italic last:mb-0",
              isUser ? "border-[#90b9df] bg-[#dceefe]" : "border-[#cfd9dc] bg-[#f6f8f8]",
            )}
          >
            {children}
          </blockquote>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className={cn("font-medium underline underline-offset-2", isUser ? "text-[#0c5577]" : "text-[#177199]")}
          >
            {children}
          </a>
        ),
        hr: () => <div className={cn("my-3 h-px", isUser ? "bg-[#b7d6f1]" : "bg-[#e5eded]")} />,
        table: ({ children }) => (
          <div className="mb-3 overflow-x-auto last:mb-0">
            <table className="min-w-full border-collapse overflow-hidden rounded-[8px] text-left text-[13px]">{children}</table>
          </div>
        ),
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
        pre: ({ children }) => <pre className="mb-3 overflow-x-auto last:mb-0">{children}</pre>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className="fade-up flex px-4">
      <div className={cn("flex w-full flex-col", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "rounded-[8px] border px-4 py-3 text-sm leading-6 break-words [overflow-wrap:anywhere]",
            isUser
              ? "max-w-[88%] border-[#c7ddf2] bg-[#e8f3ff] text-[#12394a]"
              : "w-full border-[#e7ecec] bg-white text-ink",
          )}
        >
          <MarkdownBubble content={message.text} isUser={isUser} />
        </div>

        {!isUser && message.itinerary?.length ? (
          <ItineraryCard itinerary={message.itinerary} followups={message.followups} />
        ) : null}

        {!isUser && message.debug?.tool_traces.length ? (
          <details className="mt-2 w-full rounded-2xl bg-white/60 p-2 text-xs text-[#415c60] shadow-sm">
            <summary className="cursor-pointer select-none">Debug Tool Trace</summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {message.debug.tool_traces.map((trace, index) => (
                <Badge key={`${trace.tool_name}-${index}`}>
                  {trace.phase}:{trace.tool_name}
                </Badge>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </div>
  );
}
