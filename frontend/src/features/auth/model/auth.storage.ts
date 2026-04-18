import type { AuthUser, PendingAuthMessagePayload } from "@/features/auth/model/auth.types";

const ACCESS_TOKEN_KEY = "ai-travel-access-token";
const AUTH_USER_KEY = "ai-travel-auth-user";
const PENDING_MESSAGE_KEY = "ai-travel-pending-message";

export function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setStoredAccessToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearStoredAccessToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function getStoredAuthUser(): AuthUser | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(AUTH_USER_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    window.localStorage.removeItem(AUTH_USER_KEY);
    return null;
  }
}

export function setStoredAuthUser(user: AuthUser): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

export function clearStoredAuthUser(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(AUTH_USER_KEY);
}

export function setPendingAuthMessage(payload: PendingAuthMessagePayload): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(PENDING_MESSAGE_KEY, JSON.stringify(payload));
}

export function consumePendingAuthMessage(): PendingAuthMessagePayload | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.sessionStorage.getItem(PENDING_MESSAGE_KEY);
  if (raw) {
    window.sessionStorage.removeItem(PENDING_MESSAGE_KEY);
  }
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as PendingAuthMessagePayload;
  } catch {
    return null;
  }
}
