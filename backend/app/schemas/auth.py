"""认证领域模型定义。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AuthPurpose = Literal["login", "register"]


class AuthUser(BaseModel):
    """当前登录用户信息。"""

    id: str
    email: str
    nickname: str
    created_at: str
    updated_at: str


class SendCodeRequest(BaseModel):
    """发送邮箱验证码请求。"""

    email: str = Field(min_length=5, max_length=320)
    purpose: AuthPurpose


class SendCodeResponse(BaseModel):
    """发送验证码结果。"""

    sent: bool = True
    expires_in: int


class VerifyCodeRequest(BaseModel):
    """校验邮箱验证码请求。"""

    email: str = Field(min_length=5, max_length=320)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    purpose: AuthPurpose


class AuthTokenPayload(BaseModel):
    """验证码通过后的认证结果。"""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: AuthUser
