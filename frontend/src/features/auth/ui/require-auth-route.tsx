import { useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/model/auth.context";

function AuthGateRedirect({ redirectTo }: { redirectTo: string }) {
  const navigate = useNavigate();
  const { openAuthModal } = useAuth();

  useEffect(() => {
    openAuthModal({
      redirectTo,
      initialMode: "login",
    });
    navigate("/chat", { replace: true });
  }, [navigate, openAuthModal, redirectTo]);

  return null;
}

export function RequireAuthRoute() {
  const { isAuthenticated, ready } = useAuth();
  const location = useLocation();

  if (!ready) {
    return <div className="flex h-full w-full items-center justify-center text-sm text-[#809b9f]">加载中...</div>;
  }

  if (!isAuthenticated) {
    return <AuthGateRedirect redirectTo={location.pathname} />;
  }

  return <Outlet />;
}
