import { Bell, ChevronRight, Settings, Shield, SlidersHorizontal, User } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/model/auth.context";
import {
  Button,
  ConfirmDialog,
  PageBackButton,
  SettingsGroup,
  SettingsRow,
  SettingsRowButton,
} from "@/shared/ui";

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
          <PageBackButton ariaLabel="back-profile" onClick={handleBack} />
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
          <SettingsGroup>
            <SettingsRow
              interactive
              bordered
              icon={
                <div className="rounded-full bg-blue-50 p-2 text-blue-500">
                  <Bell className="h-4 w-4" />
                </div>
              }
              title="消息通知"
              trailing={<ChevronRight className="h-4 w-4 text-[#809b9f]" />}
              className="cursor-pointer"
            />

            <SettingsRow
              interactive
              bordered
              icon={
                <div className="rounded-full bg-green-50 p-2 text-green-500">
                  <Shield className="h-4 w-4" />
                </div>
              }
              title="隐私与安全"
              trailing={<ChevronRight className="h-4 w-4 text-[#809b9f]" />}
              className="cursor-pointer"
            />

            <SettingsRowButton
              aria-label="open-permissions"
              bordered
              icon={
                <div className="rounded-full bg-[#f6efe0] p-2 text-[#7a6d58]">
                  <SlidersHorizontal className="h-4 w-4" />
                </div>
              }
              title="权限管理"
              trailing={<ChevronRight className="h-4 w-4 text-[#809b9f]" />}
              onClick={() => navigate("/profile/permissions")}
            />

            <SettingsRow
              interactive
              icon={
                <div className="rounded-full bg-gray-100 p-2 text-gray-500">
                  <Settings className="h-4 w-4" />
                </div>
              }
              title="通用设置"
              trailing={<ChevronRight className="h-4 w-4 text-[#809b9f]" />}
              className="cursor-pointer"
            />
          </SettingsGroup>

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

      <ConfirmDialog
        open={logoutConfirmOpen}
        onOpenChange={setLogoutConfirmOpen}
        title="确认退出登录"
        description="退出后将返回聊天首页，如需继续查看历史会话或个人信息，需要重新登录。"
        cancelLabel="取消"
        confirmLabel="退出登录"
        onCancel={() => setLogoutConfirmOpen(false)}
        onConfirm={handleConfirmLogout}
      />
    </>
  );
}
