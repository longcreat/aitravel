"""认证 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service, get_current_user
from app.auth.service import AuthService
from app.schemas.auth import AuthTokenPayload, AuthUser, SendCodeRequest, SendCodeResponse, VerifyCodeRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(
    payload: SendCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> SendCodeResponse:
    """发送邮箱验证码。"""
    return auth_service.send_code(email=payload.email, purpose=payload.purpose)


@router.post("/verify-code", response_model=AuthTokenPayload)
async def verify_code(
    payload: VerifyCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenPayload:
    """校验邮箱验证码并完成登录或注册。"""
    return auth_service.verify_code(email=payload.email, code=payload.code, purpose=payload.purpose)


@router.get("/me", response_model=AuthUser)
async def get_me(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """返回当前登录用户信息。"""
    return current_user
