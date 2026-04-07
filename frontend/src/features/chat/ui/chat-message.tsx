import type { ComponentPropsWithoutRef } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessageItem } from "@/features/chat/model/chat.types";
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
  return (
    <div className="max-w-none break-words text-base leading-[1.8] tracking-[0.01em] [line-break:auto] [overflow-wrap:break-word] [text-wrap:pretty] [&_*]:break-words [&_*]:[overflow-wrap:break-word]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
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
              target="_blank"
              rel="noreferrer"
              className={cn("font-medium underline underline-offset-2", isUser ? "text-[#0c5577]" : "text-[#177199]")}
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

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("fade-up flex", isUser ? "px-4" : "px-3")}>
      <div className={cn("flex w-full flex-col", isUser ? "items-end" : "items-start")}>
        {!isUser && !message.text ? (
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
            <MarkdownBubble content={message.text} isUser={isUser} />
          </div>
        )}
      </div>
    </div>
  );
}
