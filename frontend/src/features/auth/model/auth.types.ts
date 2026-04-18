export type AuthPurpose = "login" | "register";

export interface AuthUser {
  id: string;
  email: string;
  nickname: string;
  created_at: string;
  updated_at: string;
}

export interface SendCodeRequest {
  email: string;
  purpose: AuthPurpose;
}

export interface SendCodeResponse {
  sent: boolean;
  expires_in: number;
}

export interface VerifyCodeRequest {
  email: string;
  code: string;
  purpose: AuthPurpose;
}

export interface AuthTokenPayload {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
}
