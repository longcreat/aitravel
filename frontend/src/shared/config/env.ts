const defaultBaseUrl = "http://localhost:8000";

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? defaultBaseUrl,
  amapJsKey: import.meta.env.VITE_AMAP_JS_KEY ?? "",
  amapSecurityJsCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE ?? "",
};

function getEffectiveApiBaseUrl(): string {
  const configuredBase = env.apiBaseUrl.trim();

  if (typeof window === "undefined") {
    return configuredBase;
  }

  const currentHost = window.location.hostname;
  const isLocalPage = currentHost === "localhost" || currentHost === "127.0.0.1";
  const pointsToLocalBackend = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(configuredBase);

  // If a production page is accidentally built with a localhost API base,
  // fall back to the same-origin reverse-proxy path instead of breaking fetches.
  if (!isLocalPage && pointsToLocalBackend) {
    return "/api";
  }

  return configuredBase;
}

export function resolveApiUrl(endpoint: string): string {
  if (endpoint.startsWith("http")) {
    return endpoint;
  }

  const base = getEffectiveApiBaseUrl().replace(/\/+$/, "");
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;

  if (!base) {
    return path;
  }

  // Allow deployments that use "/api" as the base while callers already pass "/api/..."
  if (base.endsWith("/api") && path.startsWith("/api/")) {
    return `${base}${path.slice(4)}`;
  }

  return `${base}${path}`;
}
