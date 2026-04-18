import { env } from "@/shared/config/env";
import { getStoredAccessToken } from "@/features/auth/model/auth.storage";

interface HttpOptions extends RequestInit {
  params?: Record<string, string | number | boolean>;
}

export class HttpError extends Error {
  status: number;
  data?: unknown;

  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
    this.name = "HttpError";
  }
}

async function request<T>(endpoint: string, options: HttpOptions = {}): Promise<T> {
  const { params, headers, ...customConfig } = options;

  let url = endpoint.startsWith("http") ? endpoint : `${env.apiBaseUrl}${endpoint}`;

  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      searchParams.append(key, String(value));
    });
    url += `?${searchParams.toString()}`;
  }

  const accessToken = getStoredAccessToken();
  const config: RequestInit = {
    ...customConfig,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    let errorData;
    try {
      const data = await response.json();
      errorMessage = data.message || data.detail || errorMessage;
      errorData = data;
    } catch {
      const text = await response.text();
      errorMessage = text || errorMessage;
    }
    throw new HttpError(response.status, errorMessage, errorData);
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return (await response.json()) as T;
}

export const http = {
  get: <T>(url: string, options?: HttpOptions) => request<T>(url, { ...options, method: "GET" }),
  post: <T>(url: string, data?: unknown, options?: HttpOptions) =>
    request<T>(url, { ...options, method: "POST", body: data ? JSON.stringify(data) : undefined }),
  patch: <T>(url: string, data?: unknown, options?: HttpOptions) =>
    request<T>(url, { ...options, method: "PATCH", body: data ? JSON.stringify(data) : undefined }),
  delete: <T>(url: string, options?: HttpOptions) => request<T>(url, { ...options, method: "DELETE" }),
};
