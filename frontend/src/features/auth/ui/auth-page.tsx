import { Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { sendAuthCode, verifyAuthCode } from "@/features/auth/api/auth.api";
import { useAuth } from "@/features/auth/model/auth.context";
import type { AuthPurpose } from "@/features/auth/model/auth.types";
import { MobileShell } from "@/shared/layouts/mobile-shell";
import { Button, ConfirmDialog, FlatingInput, PageBackButton } from "@/shared/ui";

type AuthStep = "email" | "code";

export function AuthPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated, ready } = useAuth();
  const routeState = (location.state as { redirectTo?: string; initialMode?: AuthPurpose } | null) ?? null;
  const redirectTo = routeState?.redirectTo ?? "/chat";
  const initialMode = routeState?.initialMode ?? "login";

  const [mode, setMode] = useState<AuthPurpose>(initialMode);
  const [step, setStep] = useState<AuthStep>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);

  useEffect(() => {
    if (ready && isAuthenticated) {
      navigate(redirectTo, { replace: true });
    }
  }, [isAuthenticated, navigate, ready, redirectTo]);

  useEffect(() => {
    setMode(initialMode);
    setStep("email");
    setCode("");
    setError(null);
  }, [initialMode]);

  async function requestCode() {
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("请先输入邮箱");
      return false;
    }

    setSending(true);
    setError(null);
    try {
      await sendAuthCode({ email: normalizedEmail, purpose: mode });
      setStep("code");
      return true;
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "验证码发送失败");
      return false;
    } finally {
      setSending(false);
    }
  }

  async function handleVerify() {
    const normalizedEmail = email.trim();
    const normalizedCode = code.trim();
    if (!normalizedEmail || !normalizedCode) {
      setError("请填写邮箱和验证码");
      return;
    }

    setVerifying(true);
    setError(null);
    try {
      const payload = await verifyAuthCode({
        email: normalizedEmail,
        code: normalizedCode,
        purpose: mode,
      });
      login(payload.access_token, payload.user);
      navigate(redirectTo, { replace: true });
    } catch (verifyError) {
      setError(verifyError instanceof Error ? verifyError.message : "验证失败");
    } finally {
      setVerifying(false);
    }
  }

  function handleBack() {
    const hasProgress = Boolean(email.trim()) || step === "code";

    if (hasProgress) {
      setLeaveConfirmOpen(true);
      return;
    }

    navigate(-1);
  }

  function handleLeavePage() {
    setLeaveConfirmOpen(false);
    navigate(-1);
  }

  return (
    <MobileShell className="bg-paper">
      <div className="flex h-full w-full flex-col px-6 pb-8 pt-[calc(1rem+env(safe-area-inset-top))] sm:pt-16">
        <div className="flex items-center justify-between">
          <PageBackButton ariaLabel="back-auth" onClick={handleBack} />
          <div className="w-14" aria-hidden="true" />
        </div>

        <div className="flex flex-1 flex-col justify-center pb-10">
          <div className="mx-auto mb-8 flex h-20 w-20 items-center justify-center rounded-full bg-secondary text-mint">
            <Mail className="h-9 w-9" />
          </div>

          <div className="text-center">
            <h1 className="text-[30px] font-semibold tracking-[-0.03em] text-ink">
              {step === "email" ? "登录或注册" : "查看你的收件箱"}
            </h1>
            <p className="mx-auto mt-5 max-w-[320px] text-[15px] leading-8 text-muted-foreground">
              {step === "email"
                ? "使用邮箱继续，我们会通过验证码确认你的身份。"
                : `输入我们刚刚向 ${email.trim()} 发送的验证码。`}
            </p>
          </div>

          <div className="mt-10 space-y-4">
            {step === "email" ? (
              <>
                <FlatingInput
                  type="email"
                  label="电子邮件"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="h-16 rounded-[22px] border-border bg-white px-6 text-[16px] shadow-sm focus-visible:ring-0 focus-visible:ring-offset-0"
                  labelPositionerClassName="left-5"
                  labelClassName="bg-white"
                />

                {error ? <p className="px-1 text-sm text-[#b8503b]">{error}</p> : null}

                <Button
                  type="button"
                  size="hero"
                  className="bg-primary text-[18px] font-semibold text-primary-foreground hover:bg-primary/92 disabled:bg-secondary disabled:text-muted-foreground"
                  disabled={!email.trim() || sending}
                  onClick={() => void requestCode()}
                >
                  {sending ? "发送中..." : "继续"}
                </Button>
              </>
            ) : (
              <>
                <FlatingInput
                  value={code}
                  label="验证码"
                  onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                  className="h-16 rounded-[22px] border-border bg-white px-6 text-[18px] tracking-[0.08em] text-ink shadow-sm focus-visible:ring-0 focus-visible:ring-offset-0"
                  labelPositionerClassName="left-5"
                  labelClassName="bg-white"
                />

                {error ? <p className="px-1 text-sm text-[#b8503b]">{error}</p> : null}

                <Button
                  type="button"
                  size="hero"
                  className="bg-primary text-[18px] font-semibold text-primary-foreground hover:bg-primary/92 disabled:bg-secondary disabled:text-muted-foreground"
                  disabled={verifying || code.trim().length !== 6}
                  onClick={() => void handleVerify()}
                >
                  {verifying ? "验证中..." : "继续"}
                </Button>

                <div className="flex items-center gap-4 py-2 text-[14px] text-muted-foreground">
                  <div className="h-px flex-1 bg-border" />
                  <span>或</span>
                  <div className="h-px flex-1 bg-border" />
                </div>

                <Button
                  type="button"
                  variant="outline"
                  size="hero"
                  className="border-border bg-white text-[18px] font-medium text-muted-foreground hover:bg-secondary/30"
                  disabled={sending}
                  onClick={() => void requestCode()}
                >
                  {sending ? "发送中..." : "重新发送电子邮件"}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={leaveConfirmOpen}
        onOpenChange={setLeaveConfirmOpen}
        title="进度将不会保存"
        description="如果现在退出认证页面，下次需要重新填写邮箱并开始操作。"
        cancelLabel="返回"
        confirmLabel="退出"
        onCancel={() => setLeaveConfirmOpen(false)}
        onConfirm={handleLeavePage}
      />
    </MobileShell>
  );
}
