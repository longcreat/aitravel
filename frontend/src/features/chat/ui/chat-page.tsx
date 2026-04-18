import { CloudSun, Compass, List, MapPinned, MessageSquare, MoreHorizontal, Pencil, Plus, RefreshCcw, Route, Trash2, User } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "@/features/auth/model/auth.context";
import type { SessionSummary } from "@/features/chat/model/chat.types";
import { useChatAgent } from "@/features/chat/hooks/use-chat-agent";
import { ChatComposer } from "@/features/chat/ui/chat-composer";
import { ChatMessage } from "@/features/chat/ui/chat-message";
import { 
  AppSurfaceSheet,
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
  Input,
} from "@/shared/ui";
interface SessionGroup {
  label: "今日" | "7日" | "30日" | "更早";
  items: SessionSummary[];
}

type QuickPromptKind = "plan" | "weather" | "spots" | "route";

const quickPromptItems = [
  {
    kind: "plan" as const,
    icon: Compass,
    label: "规划行程",
    iconClassName: "text-mint",
  },
  {
    kind: "weather" as const,
    icon: CloudSun,
    label: "查询天气",
    iconClassName: "text-[#4db1d6]",
  },
  {
    kind: "spots" as const,
    icon: MapPinned,
    label: "推荐景点",
    iconClassName: "text-[#d1ae39]",
  },
  {
    kind: "route" as const,
    icon: Route,
    label: "规划路线",
    iconClassName: "text-[#6f72f6]",
  },
] as const;

function buildQuickPrompt(kind: QuickPromptKind) {
  switch (kind) {
    case "plan":
      return "帮我安排一个轻松的周末出游计划";
    case "weather":
      return "最近天气怎么样，适合出去玩吗？";
    case "spots":
      return "推荐几个适合放松散心的旅行地点";
    case "route":
      return "帮我规划一条轻松省心的出行路线";
    default:
      return "给我一些适合轻松出游的旅行建议";
  }
}

function getModelProfileDescription(kind: "standard" | "thinking") {
  return kind === "thinking" ? "深度推理" : "快速响应";
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
  const navigate = useNavigate();
  const { threadId: routeThreadId } = useParams<{ threadId?: string }>();
  const { openAuthModal, ready: authReady, user } = useAuth();
  const {
    threadId,
    messages,
    sessions,
    sessionsReady,
    modelProfiles,
    selectedModelProfileKey,
    selectedModelProfile,
    loading,
    error,
    isAuthenticated,
    canStartRequest,
    sendMessage,
    openSession,
    renameSessionTitle,
    removeSession,
    startNewSession,
    stopGenerating,
    regenerateLatestAssistantMessage,
    selectAssistantVersion,
    setAssistantFeedback,
    updateCurrentModelProfile,
    retryLastSubmittedMessage,
  } = useChatAgent(routeThreadId);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [deleteSessionId, setDeleteSessionId] = useState<string | null>(null);
  const [renameSessionObj, setRenameSessionObj] = useState<{ id: string; title: string } | null>(null);
  const [renameInput, setRenameInput] = useState("");
  const [modelProfileSheetOpen, setModelProfileSheetOpen] = useState(false);
  
  const listRef = useRef<HTMLDivElement | null>(null);
  const pendingNewThreadIdRef = useRef<string | null>(null);
  const openedRouteThreadIdRef = useRef<string | null>(null);
  const routeThreadIdRef = useRef(routeThreadId);
  routeThreadIdRef.current = routeThreadId;
  const groupedSessions = useMemo(() => groupSessionsByUpdatedAt(sessions), [sessions]);
  const profileInitial = useMemo(() => {
    const source = user?.nickname?.trim() || user?.email?.trim() || "我";
    return source.slice(0, 1).toUpperCase();
  }, [user?.email, user?.nickname]);
  const selectedModelProfileLabel = selectedModelProfile?.label ?? "模型";

  useEffect(() => {
    const node = listRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    if (!threadId || routeThreadIdRef.current) {
      return;
    }

    navigate(`/chat/${threadId}`, { replace: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, threadId]);

  useEffect(() => {
    if (
      pendingNewThreadIdRef.current &&
      routeThreadId === pendingNewThreadIdRef.current &&
      threadId === pendingNewThreadIdRef.current
    ) {
      pendingNewThreadIdRef.current = null;
    }
  }, [routeThreadId, threadId]);

  useEffect(() => {
    if (!authReady || !isAuthenticated || !sessionsReady || !routeThreadId) {
      return;
    }

    if (pendingNewThreadIdRef.current && routeThreadId !== pendingNewThreadIdRef.current) {
      return;
    }

    if (!sessions.some((session) => session.thread_id === routeThreadId)) {
      return;
    }

    if (openedRouteThreadIdRef.current === routeThreadId) {
      return;
    }

    openedRouteThreadIdRef.current = routeThreadId;
    void openSession(routeThreadId);
  }, [authReady, isAuthenticated, openSession, routeThreadId, sessions, sessionsReady]);

  function handleOpenSession(targetThreadId: string) {
    if (routeThreadId === targetThreadId) {
      setHistoryOpen(false);
      return;
    }

    setHistoryOpen(false);
    navigate(`/chat/${targetThreadId}`);
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

  function handleOpenHistory() {
    setHistoryOpen(true);
  }

  function handleStartNewSession(closeHistory = false) {
    const nextThreadId = startNewSession();
    pendingNewThreadIdRef.current = nextThreadId;
    openedRouteThreadIdRef.current = null;
    if (closeHistory) {
      setHistoryOpen(false);
    }
    navigate(`/chat/${nextThreadId}`);
  }

  function handleSelectModelProfile(nextProfileKey: string) {
    if (nextProfileKey === selectedModelProfileKey) {
      return;
    }
    void updateCurrentModelProfile(nextProfileKey);
  }

  function handleChooseModelProfile(nextProfileKey: string) {
    if (nextProfileKey !== selectedModelProfileKey) {
      handleSelectModelProfile(nextProfileKey);
    }
    setModelProfileSheetOpen(false);
  }

  async function handleQuickPromptClick(kind: QuickPromptKind) {
    if (!canStartRequest) {
      return;
    }

    await sendMessage(buildQuickPrompt(kind));
  }

  function handleOpenProfile() {
    setHistoryOpen(false);

    if (!authReady) {
      return;
    }

    if (!isAuthenticated) {
      openAuthModal({
        redirectTo: "/profile",
        initialMode: "login",
      });
      return;
    }

    navigate("/profile");
  }

  return (
    <div className="flex h-full w-full flex-col">

      {historyOpen ? (
        <div className={`absolute inset-0 z-30 flex ${isAuthenticated ? "bg-black/30" : "bg-transparent"}`}>
          <aside
            className={`relative h-full w-[84%] max-w-[360px] bg-white px-4 pb-4 pt-[calc(0.9rem+env(safe-area-inset-top))] sm:pt-[3.15rem] ${
              isAuthenticated ? "rounded-r-[8px]" : "border-r border-black/[0.04]"
            }`}
          >
            {isAuthenticated ? (
              <>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <Button
                    variant="ghost"
                    aria-label="new-session"
                    className="h-9 rounded-full bg-[#eee7d6] px-4 text-sm font-medium text-[#2c2b28] shadow-sm hover:bg-[#e6ddc9] active:scale-95 transition-all flex items-center gap-1.5"
                    onClick={() => handleStartNewSession(true)}
                  >
                    <Plus className="h-4 w-4 stroke-[2]" />
                    新建会话
                  </Button>

                  <button
                    type="button"
                    aria-label="open-profile"
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary text-ink shadow-sm transition-colors hover:bg-secondary/90"
                    onClick={handleOpenProfile}
                  >
                    <span className="text-sm font-semibold leading-none">{profileInitial}</span>
                  </button>
                </div>

                <div className="mb-4 h-px bg-border" />

                <div className="scrollbar-hidden h-[calc(100%-4rem)] overflow-y-auto pr-1">
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
              </>
            ) : (
              <div className="flex h-full flex-col">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <Button
                    variant="ghost"
                    aria-label="guest-new-session"
                    className="h-9 rounded-full bg-secondary px-4 text-sm font-medium text-ink shadow-sm hover:bg-secondary/90 active:scale-95 transition-all flex items-center gap-1.5"
                    onClick={() => handleStartNewSession(true)}
                  >
                    <Plus className="h-4 w-4 stroke-[2]" />
                    新建会话
                  </Button>

                  <button
                    type="button"
                    aria-label="open-profile"
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary text-mint shadow-sm transition-colors hover:bg-secondary/90"
                    onClick={handleOpenProfile}
                  >
                    <User className="h-5 w-5" />
                  </button>
                </div>

                <div className="mb-5 h-px bg-border" />

                <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
                  <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-secondary text-mint">
                    <MessageSquare className="h-8 w-8" />
                  </div>
                  <p className="text-[18px] font-semibold tracking-[-0.02em] text-ink">登录后查看历史会话</p>
                  <p className="mt-3 max-w-[240px] text-sm leading-7 text-muted-foreground">
                    你的对话记录、会话管理和跨设备继续使用，都需要先登录后才能保存。
                  </p>
                </div>

                <div className="px-2 pb-[calc(1rem+env(safe-area-inset-bottom))]">
                  <p className="mb-5 text-[15px] leading-8 text-muted-foreground">
                    登录后即可保存聊天历史。
                  </p>
                  <Button
                    type="button"
                    aria-label="login-or-register"
                    size="hero"
                    className="bg-primary text-[16px] font-semibold text-primary-foreground hover:bg-primary/92"
                    onClick={() =>
                      openAuthModal({
                        redirectTo: "/chat",
                        initialMode: "login",
                      })
                    }
                  >
                    登录或注册
                  </Button>
                </div>
              </div>
            )}
          </aside>

          <button
            type="button"
            className="h-full flex-1"
            aria-label="close-history-overlay"
            onClick={() => setHistoryOpen(false)}
          />
        </div>
      ) : null}

      <header className="relative bg-paper/80 px-4 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top))] backdrop-blur">
        <div className="relative flex h-10 items-center justify-between gap-3">
          <div className="flex min-w-[44px] items-center">
            <Button size="icon" variant="ghost" aria-label="open-history" onClick={handleOpenHistory}>
              <List className="h-5 w-5 text-mint" />
            </Button>
          </div>

          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span className="pointer-events-auto text-[20px] font-semibold tracking-[-0.02em] text-[#2c2b28]">WANDER AI</span>
          </div>

          <div className="flex min-w-[76px] justify-end">
            {!authReady ? (
              <div className="h-10 w-[76px]" aria-hidden="true" />
            ) : isAuthenticated ? (
              <Button 
                size="icon" 
                variant="ghost" 
                aria-label="new-session" 
                className="rounded-full bg-white/85 shadow-sm hover:bg-white"
                onClick={() => handleStartNewSession()}
              >
                <Plus className="h-5 w-5 text-mint" />
              </Button>
            ) : (
              <Button
                type="button"
                aria-label="login"
                className="h-10 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/92"
                onClick={() =>
                  openAuthModal({
                    redirectTo: "/chat",
                    initialMode: "login",
                  })
                }
              >
                登录
              </Button>
            )}
          </div>
        </div>
      </header>

      <section ref={listRef} className="scrollbar-hidden relative flex-1 space-y-4 overflow-y-auto py-4">
        {messages.length === 0 ? (
          <div className="flex min-h-full flex-col items-center justify-center px-6 pb-16 pt-6 text-center">
            <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-ink">有什么可以帮忙的？</h2>
            <div className="mt-6 grid w-full max-w-[320px] grid-cols-2 gap-3">
              {quickPromptItems.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.label}
                    type="button"
                    aria-label={`quick-prompt-${item.label}`}
                    disabled={!canStartRequest}
                    className="flex items-center gap-2 rounded-full border border-border bg-white px-4 py-3 text-left text-[15px] font-medium text-[#6d6a64] shadow-sm transition-colors hover:bg-secondary/40 disabled:cursor-not-allowed disabled:opacity-70"
                    onClick={() => void handleQuickPromptClick(item.kind)}
                  >
                    <Icon className={`h-5 w-5 shrink-0 ${item.iconClassName}`} />
                    <span className="truncate">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            message={message}
            onRegenerate={regenerateLatestAssistantMessage}
            onSwitchVersion={selectAssistantVersion}
            onFeedback={setAssistantFeedback}
          />
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

      <ChatComposer
        loading={loading}
        ready={authReady}
        modelProfileLabel={selectedModelProfileLabel}
        onSend={sendMessage}
        onOpenModelProfileSheet={() => setModelProfileSheetOpen(true)}
        onStop={stopGenerating}
      />

      <AppSurfaceSheet
        open={modelProfileSheetOpen}
        onClose={() => setModelProfileSheetOpen(false)}
        title="选择模型"
        description="根据问题复杂度切换响应模式。"
        className="inset-x-auto bottom-4 left-1/2 w-[calc(100%-2.5rem)] max-w-[392px] -translate-x-1/2 rounded-[32px] border-none px-5 pb-5 pt-10 sm:bottom-6"
        descriptionClassName="mt-3 text-[14px] leading-6"
        closeButtonClassName="right-4 top-4 h-9 w-9 p-0 leading-none opacity-100 [&>svg]:h-5 [&>svg]:w-5 [&>svg]:shrink-0"
        closeLabel="model-profile-sheet-close"
      >
        <div className="space-y-2.5">
          {modelProfiles.map((profile) => {
            const isSelected = profile.key === selectedModelProfileKey;

            return (
              <button
                key={profile.key}
                type="button"
                aria-label={`model-profile-option-${profile.key}`}
                aria-pressed={isSelected}
                className={`w-full rounded-[22px] border px-5 py-3.5 text-left transition-colors ${
                  isSelected
                    ? "border-[#eadfc9] bg-[#f6efe0] shadow-sm"
                    : "border-border bg-white hover:bg-secondary/30"
                }`}
                onClick={() => handleChooseModelProfile(profile.key)}
              >
                <div className="flex min-w-0 items-baseline gap-3">
                  <span className={`text-[18px] font-semibold tracking-[-0.02em] ${isSelected ? "text-ink" : "text-[#3b3935]"}`}>
                    {profile.label}
                  </span>
                  <span className={`text-[14px] leading-5 ${isSelected ? "text-[#7a6d58]" : "text-muted-foreground"}`}>
                    {getModelProfileDescription(profile.kind)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </AppSurfaceSheet>

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
