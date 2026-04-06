import { Compass, History, MoreHorizontal, Pencil, Plus, RefreshCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SessionSummary } from "@/features/chat/model/chat.types";
import { useChatAgent } from "@/features/chat/hooks/use-chat-agent";
import { ChatComposer } from "@/features/chat/ui/chat-composer";
import { ChatMessage } from "@/features/chat/ui/chat-message";
import { MobileShell } from "@/shared/layouts/mobile-shell";
import { Button } from "@/shared/ui";

interface SessionGroup {
  label: "今日" | "7日" | "30日" | "更早";
  items: SessionSummary[];
}

function groupSessionsByUpdatedAt(sessions: SessionSummary[]): SessionGroup[] {
  const groups: SessionGroup[] = [
    { label: "今日", items: [] },
    { label: "7日", items: [] },
    { label: "30日", items: [] },
    { label: "更早", items: [] },
  ];

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayMs = 24 * 60 * 60 * 1000;

  for (const session of sessions) {
    const updated = new Date(session.updated_at);
    const startOfUpdated = new Date(updated.getFullYear(), updated.getMonth(), updated.getDate()).getTime();
    const diffDays = Math.floor((startOfToday - startOfUpdated) / dayMs);

    if (diffDays <= 0) {
      groups[0].items.push(session);
      continue;
    }
    if (diffDays <= 7) {
      groups[1].items.push(session);
      continue;
    }
    if (diffDays <= 30) {
      groups[2].items.push(session);
      continue;
    }
    groups[3].items.push(session);
  }

  return groups.filter((group) => group.items.length > 0);
}

export function ChatPage() {
  const {
    threadId,
    messages,
    sessions,
    loading,
    error,
    sendMessage,
    openSession,
    renameSessionTitle,
    removeSession,
    startNewSession,
  } = useChatAgent();

  const [historyOpen, setHistoryOpen] = useState(false);
  const [menuThreadId, setMenuThreadId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const groupedSessions = useMemo(() => groupSessionsByUpdatedAt(sessions), [sessions]);

  useEffect(() => {
    const node = listRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [messages, loading]);

  async function handleOpenSession(targetThreadId: string) {
    setMenuThreadId(null);
    await openSession(targetThreadId);
    setHistoryOpen(false);
  }

  async function handleRenameSession(targetThreadId: string, currentTitle: string) {
    const nextTitle = window.prompt("请输入会话新名称", currentTitle);
    if (!nextTitle) {
      return;
    }
    await renameSessionTitle(targetThreadId, nextTitle);
    setMenuThreadId(null);
  }

  async function handleDeleteSession(targetThreadId: string) {
    const confirmed = window.confirm("确认删除该会话吗？");
    if (!confirmed) {
      return;
    }
    await removeSession(targetThreadId);
    setMenuThreadId(null);
  }

  return (
    <MobileShell>

      {historyOpen ? (
        <div className="absolute inset-0 z-30 flex bg-black/30">
          <aside className="relative h-full w-[84%] max-w-[360px] bg-white px-4 pb-4 pt-[calc(0.9rem+env(safe-area-inset-top))]">
            <div className="mb-3 flex items-center justify-between">
              <Button
                size="icon"
                variant="ghost"
                aria-label="new-session"
                className="bg-[#ece3d5] shadow-sm hover:bg-[#e4d9c9]"
                onClick={startNewSession}
              >
                <Plus className="h-4 w-4" />
              </Button>
              <Button size="icon" variant="ghost" aria-label="close-history" onClick={() => setHistoryOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="scrollbar-hidden h-[calc(100%-3rem)] overflow-y-auto pr-1">
              {groupedSessions.map((group) => (
                <section key={group.label} className="mb-4">
                  <p className="mb-2 text-xs font-semibold text-[#47686d]">{group.label}</p>
                  <div className="space-y-2">
                    {group.items.map((session) => (
                      <div key={session.thread_id} className="relative rounded-[8px] bg-white px-2.5 py-0.5 shadow-sm">
                        <div className="flex min-h-[30px] items-center gap-2">
                          <button
                            type="button"
                            className="flex min-w-0 flex-1 items-center py-0.5 text-left"
                            onClick={() => void handleOpenSession(session.thread_id)}
                          >
                            <p className="truncate text-[15px] font-medium leading-none text-ink">
                              {session.title}
                              {session.thread_id === threadId ? " · 当前" : ""}
                            </p>
                          </button>

                          <button
                            type="button"
                            className="shrink-0 p-0.5 text-[#5f7a7e]"
                            aria-label={`session-menu-${session.thread_id}`}
                            onClick={() =>
                              setMenuThreadId((current) => (current === session.thread_id ? null : session.thread_id))
                            }
                          >
                            <MoreHorizontal className="h-4 w-4" />
                          </button>
                        </div>

                        {menuThreadId === session.thread_id ? (
                          <div className="absolute right-2 top-9 z-10 w-[128px] rounded-xl bg-white p-1 shadow-lg">
                            <button
                              type="button"
                              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-xs text-ink hover:bg-[#f4f7f7]"
                              onClick={() => void handleRenameSession(session.thread_id, session.title)}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                              重命名
                            </button>
                            <button
                              type="button"
                              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-xs text-[#8d3b2f] hover:bg-[#fff0ee]"
                              onClick={() => void handleDeleteSession(session.thread_id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              删除
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </aside>

          <button
            type="button"
            className="h-full flex-1"
            aria-label="close-history-overlay"
            onClick={() => setHistoryOpen(false)}
          />
        </div>
      ) : null}

      <header className="relative bg-paper/80 px-4 pb-3 pt-[calc(0.9rem+env(safe-area-inset-top))] backdrop-blur">
        <div className="flex items-center justify-between">
          <Button size="icon" variant="ghost" aria-label="open-history" onClick={() => setHistoryOpen(true)}>
            <History className="h-5 w-5 text-mint" />
          </Button>
          <div className="rounded-full bg-white/85 p-2 shadow-sm">
            <Compass className="h-5 w-5 text-mint" />
          </div>
        </div>
      </header>

      <section ref={listRef} className="scrollbar-hidden relative flex-1 space-y-4 overflow-y-auto py-4">
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}

        {error ? (
          <div className="px-4">
            <div className="flex items-center justify-between rounded-2xl bg-[#fff0ee] px-3 py-2 text-xs text-[#8d3b2f] shadow-sm">
              <span className="mr-2 truncate">请求失败：{error}</span>
              <Button variant="ghost" size="sm" onClick={() => void sendMessage("请继续刚才的建议")}>
                <RefreshCcw className="mr-1 h-3.5 w-3.5" />
                重试
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      <ChatComposer loading={loading} onSend={sendMessage} />
    </MobileShell>
  );
}
