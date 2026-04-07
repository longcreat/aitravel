import { Compass, History, MessageSquare, MoreHorizontal, Pencil, Plus, RefreshCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SessionSummary } from "@/features/chat/model/chat.types";
import { useChatAgent } from "@/features/chat/hooks/use-chat-agent";
import { ChatComposer } from "@/features/chat/ui/chat-composer";
import { ChatMessage } from "@/features/chat/ui/chat-message";
import { 
  Button, 
  DropdownMenu, 
  DropdownMenuContent, 
  DropdownMenuItem, 
  DropdownMenuTrigger,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Input
} from "@/shared/ui";

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
    stopGenerating,
    retryLastSubmittedMessage,
  } = useChatAgent();

  const [historyOpen, setHistoryOpen] = useState(false);
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  const [renameSessionObj, setRenameSessionObj] = useState<{ id: string; title: string } | null>(null);
  const [renameInput, setRenameInput] = useState("");
  
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
    await openSession(targetThreadId);
    setHistoryOpen(false);
  }

  function handleRenameSession(targetThreadId: string, currentTitle: string) {
    setRenameInput(currentTitle);
    setRenameSessionObj({ id: targetThreadId, title: currentTitle });
  }

  async function submitRename() {
    if (!renameSessionObj || !renameInput.trim() || renameInput === renameSessionObj.title) {
      setRenameSessionObj(null);
      return;
    }
    await renameSessionTitle(renameSessionObj.id, renameInput.trim());
    setRenameSessionObj(null);
  }

  function handleDeleteSession(targetThreadId: string) {
    setDeleteSessionId(targetThreadId);
  }

  async function confirmDeleteSession() {
    if (!deleteSessionId) return;
    await removeSession(deleteSessionId);
    setDeleteSessionId(null);
  }

  return (
    <div className="flex h-full w-full flex-col">

      {historyOpen ? (
        <div className="absolute inset-0 z-30 flex bg-black/30">
          <aside className="relative h-full w-[84%] max-w-[360px] rounded-r-[8px] bg-white px-4 pb-4 pt-[calc(0.9rem+env(safe-area-inset-top))] sm:pt-[3.15rem]">
            <div className="mb-3 flex items-center justify-between">
              <Button
                variant="ghost"
                aria-label="new-session"
                className="h-9 rounded-full bg-[#eee7d6] px-4 text-sm font-medium text-[#2c2b28] shadow-sm hover:bg-[#e6ddc9] active:scale-95 transition-all flex items-center gap-1.5"
                onClick={startNewSession}
              >
                <Plus className="h-4 w-4 stroke-[2]" />
                新建会话
              </Button>
              <Button size="icon" variant="ghost" aria-label="close-history" onClick={() => setHistoryOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="scrollbar-hidden h-[calc(100%-3rem)] overflow-y-auto pr-1">
              {groupedSessions.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center text-[#a29f98] pb-20">
                  <MessageSquare className="mb-4 h-12 w-12 opacity-20" />
                  <p className="text-sm font-medium">暂无历史会话</p>
                  <p className="mt-1.5 text-[13px] opacity-60">随时开启你的新旅行对话</p>
                </div>
              ) : (
                groupedSessions.map((group) => (
                <section key={group.label} className="mb-4">
                  <p className="mb-2 text-xs font-semibold text-[#47686d]">{group.label}</p>
                  <div className="space-y-2">
                    {group.items.map((session) => (
                      <div key={session.thread_id} className="group relative rounded-lg px-2 hover:bg-black/5 transition-colors -mx-2">
                        <div className="flex min-h-[36px] items-center gap-2">
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

                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                className="shrink-0 rounded-md p-0.5 text-[#5f7a7e] outline-none hover:bg-black/5 data-[state=open]:bg-black/5"
                                aria-label={`session-menu-${session.thread_id}`}
                              >
                                <MoreHorizontal className="h-4 w-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-[128px] rounded-xl p-1 shadow-lg">
                              <DropdownMenuItem
                                className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-xs text-ink focus:bg-[#f4f7f7]"
                                onClick={() => void handleRenameSession(session.thread_id, session.title)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                重命名
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-xs text-[#8d3b2f] focus:bg-[#fff0ee] focus:text-[#8d3b2f]"
                                onClick={() => void handleDeleteSession(session.thread_id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                删除
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ))
              )}
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
              <Button variant="ghost" size="sm" onClick={() => void retryLastSubmittedMessage()}>
                <RefreshCcw className="mr-1 h-3.5 w-3.5" />
                重试
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      <ChatComposer loading={loading} onSend={sendMessage} onStop={stopGenerating} />

      <Dialog open={!!deleteSessionId} onOpenChange={(open) => !open && setDeleteSessionId(null)}>
        <DialogContent className="max-w-[320px]">
          <DialogHeader>
            <DialogTitle>删除会话</DialogTitle>
            <DialogDescription>
              确定要删除此对话吗？此操作不可逆。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-row sm:justify-end gap-2 pt-2">
            <Button variant="outline" className="flex-1 sm:flex-none" onClick={() => setDeleteSessionId(null)}>取消</Button>
            <Button variant="destructive" className="flex-1 sm:flex-none" onClick={() => void confirmDeleteSession()}>确定删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!renameSessionObj} onOpenChange={(open) => !open && setRenameSessionObj(null)}>
        <DialogContent className="max-w-[320px]">
          <DialogHeader>
            <DialogTitle>重命名会话</DialogTitle>
            <DialogDescription className="hidden">输入一个新的名字</DialogDescription>
          </DialogHeader>
          <div className="py-2">
            <Input 
              value={renameInput} 
              onChange={(e) => setRenameInput(e.target.value)} 
              placeholder="新的会话名称" 
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitRename();
              }}
            />
          </div>
          <DialogFooter className="flex-row sm:justify-end gap-2">
            <Button variant="outline" className="flex-1 sm:flex-none" onClick={() => setRenameSessionObj(null)}>取消</Button>
            <Button className="flex-1 sm:flex-none" onClick={() => void submitRename()}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
}
