import { ArrowLeft, Bell, ChevronRight, Settings, Shield, User } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/model/auth.context";
import { Button, Dialog, DialogContent, DialogDescription, DialogTitle } from "@/shared/ui";

export function ProfilePage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [logoutConfirmOpen, setLogoutConfirmOpen] = useState(false);

  function handleConfirmLogout() {
    setLogoutConfirmOpen(false);
    logout();
    navigate("/chat", { replace: true });
  }

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigate("/chat", { replace: true });
  }

  return (
    <>
      <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
        <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="back-profile"
            className="h-14 w-14 rounded-full bg-white shadow-sm hover:bg-secondary/50"
            onClick={handleBack}
          >
            <ArrowLeft className="h-7 w-7 text-ink" />
          </Button>
        </div>

        {/* Header Profile Info */}
        <section className="flex flex-col items-center px-6 pb-6 pt-6">
          <div className="relative mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-[#f4ebd9] shadow-sm">
            <User className="h-10 w-10 text-[#d4704e]" />
          </div>
          <h2 className="text-xl font-bold text-ink">{user?.nickname ?? "旅行用户"}</h2>
          <p className="mt-1 text-sm text-[#809b9f]">{user?.email ?? "尚未登录"}</p>
        </section>

        {/* Action List */}
        <section className="flex-1 px-4 pb-8">
          <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
            <div className="flex cursor-pointer items-center justify-between border-b px-4 py-4 transition-colors hover:bg-black/5">
              <div className="flex items-center gap-3">
                <div className="rounded-full bg-blue-50 p-2 text-blue-500">
                  <Bell className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-ink">消息通知</span>
              </div>
              <ChevronRight className="h-4 w-4 text-[#809b9f]" />
            </div>

            <div className="flex cursor-pointer items-center justify-between border-b px-4 py-4 transition-colors hover:bg-black/5">
              <div className="flex items-center gap-3">
                <div className="rounded-full bg-green-50 p-2 text-green-500">
                  <Shield className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-ink">隐私与安全</span>
              </div>
              <ChevronRight className="h-4 w-4 text-[#809b9f]" />
            </div>

            <div className="flex cursor-pointer items-center justify-between px-4 py-4 transition-colors hover:bg-black/5">
              <div className="flex items-center gap-3">
                <div className="rounded-full bg-gray-100 p-2 text-gray-500">
                  <Settings className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-ink">通用设置</span>
              </div>
              <ChevronRight className="h-4 w-4 text-[#809b9f]" />
            </div>
          </div>

          <div className="mt-6 flex justify-center">
            <Button
              variant="outline"
              className="w-[80%] rounded-xl border-[#d4704e]/30 text-[#d4704e] hover:bg-[#d4704e]/10"
              onClick={() => setLogoutConfirmOpen(true)}
            >
              退出登录
            </Button>
          </div>
        </section>
      </div>

      <Dialog open={logoutConfirmOpen} onOpenChange={setLogoutConfirmOpen}>
        <DialogContent className="w-[calc(100%-2.5rem)] max-w-[380px] rounded-[28px] border-none bg-white px-7 pb-7 pt-7 sm:rounded-[28px] [&>button]:hidden">
          <DialogTitle className="text-left text-[20px] font-semibold tracking-[-0.02em] text-ink">
            确认退出登录
          </DialogTitle>
          <DialogDescription className="mt-4 text-left text-[15px] leading-7 text-muted-foreground">
            退出后将返回聊天首页，如需继续查看历史会话或个人信息，需要重新登录。
          </DialogDescription>

          <div className="mt-8 flex items-center justify-end gap-8">
            <button
              type="button"
              className="text-[16px] font-medium text-muted-foreground"
              onClick={() => setLogoutConfirmOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="text-[16px] font-semibold text-ink"
              onClick={handleConfirmLogout}
            >
              退出登录
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
