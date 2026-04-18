import type {
  AuthTokenPayload,
  AuthUser,
  SendCodeRequest,
  SendCodeResponse,
  VerifyCodeRequest,
} from "@/features/auth/model/auth.types";
import { http } from "@/shared/lib/http";

export async function sendAuthCode(payload: SendCodeRequest): Promise<SendCodeResponse> {
  return http.post<SendCodeResponse>("/api/auth/send-code", payload);
}

export async function verifyAuthCode(payload: VerifyCodeRequest): Promise<AuthTokenPayload> {
  return http.post<AuthTokenPayload>("/api/auth/verify-code", payload);
}

export async function getCurrentUser(): Promise<AuthUser> {
  return http.get<AuthUser>("/api/auth/me");
}
