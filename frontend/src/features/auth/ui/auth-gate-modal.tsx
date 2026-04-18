import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/shared/ui";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/model/auth.context";
import type { AuthPurpose } from "@/features/auth/model/auth.types";
import { Button } from "@/shared/ui";

function buttonClassName(isPrimary: boolean) {
  return isPrimary
    ? "h-14 w-full rounded-full bg-primary text-[16px] font-semibold text-primary-foreground hover:bg-primary/92"
    : "h-14 w-full rounded-full border border-border bg-white text-[16px] font-semibold text-ink hover:bg-secondary/40";
}

export function AuthGateModal() {
  const navigate = useNavigate();
  const { authGate, closeAuthModal } = useAuth();

  function handleOpenAuth(mode: AuthPurpose) {
    closeAuthModal();
    navigate("/auth", {
      state: {
        redirectTo: authGate.redirectTo,
        initialMode: mode,
      },
    });
  }

  const registerPrimary = authGate.initialMode === "register";

  return (
    <Dialog open={authGate.open} onOpenChange={(open) => !open && closeAuthModal()}>
      <DialogContent className="top-auto bottom-4 w-[calc(100%-2.5rem)] max-w-[392px] translate-x-[-50%] translate-y-0 rounded-[32px] border-none bg-white px-6 pb-6 pt-12 sm:bottom-6 sm:rounded-[32px] [&>button]:right-5 [&>button]:top-5 [&>button]:inline-flex [&>button]:h-10 [&>button]:w-10 [&>button]:items-center [&>button]:justify-center [&>button]:rounded-full [&>button]:p-0 [&>button]:leading-none [&>button]:opacity-100 [&>button_svg]:h-5 [&>button_svg]:w-5 [&>button_svg]:shrink-0">
        <div className="text-center">
          <DialogTitle className="text-[20px] font-semibold tracking-[-0.02em] text-ink">登录或创建账户</DialogTitle>
          <DialogDescription className="mt-4 text-[15px] leading-8 text-muted-foreground">
            登录后即可保存聊天历史，并继续使用你的旅行助手。
          </DialogDescription>
        </div>

        <div className="mt-8 space-y-3">
          <Button
            type="button"
            aria-label="auth-gate-register"
            className={buttonClassName(registerPrimary)}
            onClick={() => handleOpenAuth("register")}
          >
            注册
          </Button>
          <Button
            type="button"
            aria-label="auth-gate-login"
            className={buttonClassName(!registerPrimary)}
            onClick={() => handleOpenAuth("login")}
          >
            登录
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
