"""认证服务。"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from hashlib import sha256
from pathlib import Path

import jwt
from fastapi import HTTPException, status

from app.auth.store import AuthSQLiteStore
from app.schemas.auth import AuthPurpose, AuthTokenPayload, AuthUser, SendCodeResponse

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


@dataclass
class SMTPSettings:
    """SMTP 发信配置。"""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool


class AuthService:
    """邮箱验证码登录服务。"""

    def __init__(self, sqlite_db_path: Path) -> None:
        self._store = AuthSQLiteStore(sqlite_db_path)
        self._jwt_secret = os.getenv("JWT_SECRET", "dev-jwt-secret")
        self._jwt_expire_days = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
        self._code_expire_minutes = int(os.getenv("AUTH_CODE_EXPIRE_MINUTES", "10"))
        self._smtp_settings = self._load_smtp_settings()

    def _load_smtp_settings(self) -> SMTPSettings | None:
        host = os.getenv("SMTP_HOST", "").strip()
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "").strip()
        from_email = os.getenv("SMTP_FROM", "").strip()
        if not all([host, username, password, from_email]):
            return None
        return SMTPSettings(
            host=host,
            port=int(os.getenv("SMTP_PORT", "587")),
            username=username,
            password=password,
            from_email=from_email,
            use_tls=os.getenv("SMTP_USE_TLS", "true").strip().lower() != "false",
        )

    def _should_use_smtp_ssl(self) -> bool:
        """判断当前 SMTP 配置是否应走 SSL 直连。

        常见的 SSL 端口除了 465，还包括部分企业邮箱使用的 994。
        这两类端口都应该直接使用 `SMTP_SSL`，而不是先建普通连接再 `STARTTLS`。
        """

        if self._smtp_settings is None:
            return False
        return self._smtp_settings.use_tls and self._smtp_settings.port in {465, 994}

    def _normalize_email(self, email: str) -> str:
        normalized = email.strip().lower()
        if not _EMAIL_PATTERN.match(normalized):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="邮箱格式不正确")
        return normalized

    def _hash_code(self, email: str, purpose: AuthPurpose, code: str) -> str:
        payload = f"{email}:{purpose}:{code}:{self._jwt_secret}".encode("utf-8")
        return sha256(payload).hexdigest()

    def _build_access_token(self, user: AuthUser) -> str:
        expires_at = _utc_now() + timedelta(days=self._jwt_expire_days)
        return jwt.encode(
            {
                "sub": user.id,
                "email": user.email,
                "exp": expires_at,
                "iat": _utc_now(),
            },
            self._jwt_secret,
            algorithm="HS256",
        )

    def _send_email(self, *, email: str, code: str, purpose: AuthPurpose) -> None:
        if self._smtp_settings is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SMTP 未配置，暂时无法发送验证码",
            )

        action_text = "登录" if purpose == "login" else "注册"
        message = EmailMessage()
        message["From"] = self._smtp_settings.from_email
        message["To"] = email
        message["Subject"] = f"AI Travel Agent {action_text}验证码"
        message.set_content(
            f"你的 {action_text} 验证码是：{code}\n"
            f"验证码 {self._code_expire_minutes} 分钟内有效，请勿泄露给他人。\n",
            subtype="plain",
            charset="utf-8",
        )

        # 企业邮箱常见的 SSL 端口可能是 465 或 994，这两种都需要直接走 SMTP_SSL。
        if self._should_use_smtp_ssl():
            with smtplib.SMTP_SSL(self._smtp_settings.host, self._smtp_settings.port, timeout=20) as smtp:
                smtp.login(self._smtp_settings.username, self._smtp_settings.password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(self._smtp_settings.host, self._smtp_settings.port, timeout=20) as smtp:
            smtp.ehlo()
            if self._smtp_settings.use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(self._smtp_settings.username, self._smtp_settings.password)
            smtp.send_message(message)

    def send_code(self, *, email: str, purpose: AuthPurpose) -> SendCodeResponse:
        normalized_email = self._normalize_email(email)
        existing_user = self._store.get_user_by_email(normalized_email)

        if purpose == "login" and existing_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱尚未注册")
        if purpose == "register" and existing_user is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册，请直接登录")

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = (_utc_now() + timedelta(minutes=self._code_expire_minutes)).isoformat()
        self._store.save_email_code(
            email=normalized_email,
            purpose=purpose,
            code_hash=self._hash_code(normalized_email, purpose, code),
            expires_at=expires_at,
        )
        self._send_email(email=normalized_email, code=code, purpose=purpose)
        return SendCodeResponse(expires_in=self._code_expire_minutes * 60)

    def verify_code(self, *, email: str, code: str, purpose: AuthPurpose) -> AuthTokenPayload:
        normalized_email = self._normalize_email(email)
        stored = self._store.get_latest_email_code(email=normalized_email, purpose=purpose)
        if stored is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先发送验证码")
        if stored["consumed_at"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已失效，请重新获取")
        if datetime.fromisoformat(str(stored["expires_at"])) < _utc_now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新获取")

        expected_hash = self._hash_code(normalized_email, purpose, code)
        if not hmac.compare_digest(expected_hash, str(stored["code_hash"])):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

        user = self._store.get_user_by_email(normalized_email)
        if purpose == "login":
            if user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱尚未注册")
        else:
            if user is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册，请直接登录")
            user = self._store.create_user(normalized_email)

        self._store.consume_email_code(int(stored["id"]))
        assert user is not None
        return AuthTokenPayload(access_token=self._build_access_token(user), user=user)

    def get_current_user(self, token: str) -> AuthUser:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效") from exc

        user_id = str(payload.get("sub", "")).strip()
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")

        user = self._store.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
        return user
