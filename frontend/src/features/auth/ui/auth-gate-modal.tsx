import { useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/model/auth.context";
import type { AuthPurpose } from "@/features/auth/model/auth.types";
import { AppSurfaceSheet, Button } from "@/shared/ui";

function buttonClassName(isPrimary: boolean) {
  return isPrimary
    ? "bg-primary text-[16px] font-semibold text-primary-foreground hover:bg-primary/92"
    : "border border-border bg-white text-[16px] font-semibold text-ink hover:bg-secondary/40";
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
    <AppSurfaceSheet
      open={authGate.open}
      onClose={closeAuthModal}
      className="inset-x-auto bottom-4 left-1/2 w-[calc(100%-2.5rem)] max-w-[392px] -translate-x-1/2 rounded-[32px] border-none px-6 pb-6 pt-12 sm:bottom-6"
      closeButtonClassName="right-5 top-5 h-10 w-10 p-0 leading-none opacity-100 [&>svg]:h-5 [&>svg]:w-5 [&>svg]:shrink-0"
    >
        <div className="text-center">
          <h2 className="text-[20px] font-semibold tracking-[-0.02em] text-ink">登录或创建账户</h2>
          <p className="mt-4 text-[15px] leading-8 text-muted-foreground">
            登录后即可保存聊天历史，并继续使用你的旅行助手。
          </p>
        </div>

        <div className="mt-8 space-y-3">
          <Button
            type="button"
            aria-label="auth-gate-register"
            size="hero"
            className={buttonClassName(registerPrimary)}
            onClick={() => handleOpenAuth("register")}
          >
            注册
          </Button>
          <Button
            type="button"
            aria-label="auth-gate-login"
            size="hero"
            className={buttonClassName(!registerPrimary)}
            onClick={() => handleOpenAuth("login")}
          >
            登录
          </Button>
        </div>
    </AppSurfaceSheet>
  );
}
