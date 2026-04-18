import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getCurrentUser } from "@/features/auth/api/auth.api";
import {
  clearStoredAuthUser,
  clearStoredAccessToken,
  getStoredAuthUser,
  getStoredAccessToken,
  setPendingAuthMessage,
  setStoredAuthUser,
  setStoredAccessToken,
} from "@/features/auth/model/auth.storage";
import type { AuthPurpose, AuthUser, PendingAuthMessagePayload } from "@/features/auth/model/auth.types";
import { HttpError } from "@/shared/lib/http";

interface AuthGateState {
  open: boolean;
  redirectTo: string;
  initialMode: AuthPurpose;
}

interface OpenAuthModalOptions {
  redirectTo?: string;
  initialMode?: AuthPurpose;
  pendingMessage?: PendingAuthMessagePayload;
}

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  ready: boolean;
  authGate: AuthGateState;
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
  refreshMe: () => Promise<void>;
  openAuthModal: (options?: OpenAuthModalOptions) => void;
  closeAuthModal: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  const [authGate, setAuthGate] = useState<AuthGateState>({
    open: false,
    redirectTo: "/chat",
    initialMode: "login",
  });

  const closeAuthModal = useCallback(() => {
    setAuthGate((current) => ({ ...current, open: false }));
  }, []);

  const openAuthModal = useCallback((options?: OpenAuthModalOptions) => {
    if (options?.pendingMessage) {
      setPendingAuthMessage(options.pendingMessage);
    }

    setAuthGate({
      open: true,
      redirectTo: options?.redirectTo ?? "/chat",
      initialMode: options?.initialMode ?? "login",
    });
  }, []);

  const logout = useCallback(() => {
    clearStoredAuthUser();
    clearStoredAccessToken();
    setUser(null);
    setAuthGate({
      open: false,
      redirectTo: "/chat",
      initialMode: "login",
    });
  }, []);

  const refreshMe = useCallback(async () => {
    const token = getStoredAccessToken();
    if (!token) {
      clearStoredAuthUser();
      setUser(null);
      setReady(true);
      return;
    }

    const cachedUser = getStoredAuthUser();
    if (cachedUser) {
      setUser(cachedUser);
    }

    try {
      const nextUser = await getCurrentUser();
      setStoredAuthUser(nextUser);
      setUser(nextUser);
    } catch (error) {
      if (error instanceof HttpError && (error.status === 401 || error.status === 403)) {
        clearStoredAccessToken();
        clearStoredAuthUser();
        setUser(null);
      } else if (!cachedUser) {
        setUser(null);
      }
    } finally {
      setReady(true);
    }
  }, []);

  const login = useCallback((token: string, nextUser: AuthUser) => {
    setStoredAccessToken(token);
    setStoredAuthUser(nextUser);
    setUser(nextUser);
    setReady(true);
    setAuthGate({
      open: false,
      redirectTo: "/chat",
      initialMode: "login",
    });
  }, []);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      ready,
      authGate,
      login,
      logout,
      refreshMe,
      openAuthModal,
      closeAuthModal,
    }),
    [authGate, closeAuthModal, login, logout, openAuthModal, ready, refreshMe, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return context;
}
