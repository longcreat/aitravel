"""认证服务。"""

from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import socket
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
_LOGGER = logging.getLogger(__name__)


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
        self._jwt_secret = self._load_jwt_secret()
        self._jwt_expire_days = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
        self._code_expire_minutes = int(os.getenv("AUTH_CODE_EXPIRE_MINUTES", "10"))
        self._smtp_settings = self._load_smtp_settings()

    def _load_jwt_secret(self) -> str:
        """读取并校验 JWT 密钥。"""
        secret = os.getenv("JWT_SECRET", "").strip()
        if not secret:
            raise RuntimeError("JWT_SECRET 未配置，认证服务无法启动")
        return secret

    def _load_smtp_settings(self) -> SMTPSettings | None:
        host = os.getenv("SMTP_HOST", "").strip()
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "").strip()
        # docker compose env_file may pass a literal "\$" into the container for passwords containing "$".
        password = password.replace("\\$", "$")
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

    def _smtp_mode(self) -> str:
        if self._should_use_smtp_ssl():
            return "ssl"
        if self._smtp_settings is not None and self._smtp_settings.use_tls:
            return "starttls"
        return "plain"

    def _raise_smtp_failure(self, exc: Exception) -> None:
        assert self._smtp_settings is not None
        _LOGGER.exception(
            "SMTP send failed host=%s port=%s mode=%s",
            self._smtp_settings.host,
            self._smtp_settings.port,
            self._smtp_mode(),
        )
        if isinstance(exc, socket.gaierror):
            detail = "SMTP 域名解析失败，请检查 SMTP_HOST 和本机 DNS 配置"
        elif isinstance(exc, smtplib.SMTPAuthenticationError):
            detail = "SMTP 认证失败，请检查 SMTP_USERNAME 与 SMTP_PASSWORD，部分邮箱需要客户端授权码"
        elif isinstance(exc, smtplib.SMTPServerDisconnected):
            detail = "SMTP 连接被服务端断开，请检查 SMTP_HOST、SMTP_PORT 与 SSL/TLS 模式是否匹配"
        elif isinstance(exc, (socket.timeout, TimeoutError)):
            detail = "SMTP 连接超时，请检查网络、防火墙和 SMTP 端口策略"
        else:
            detail = "SMTP 发送失败，请检查 SMTP 配置和当前网络状态"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

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

    def _build_email_subject(self, code: str) -> str:
        """构建验证码邮件主题。"""
        return f"你的 WANDER AI 代码为 {code}"

    def _build_email_text_body(self, *, email: str, code: str, purpose: AuthPurpose) -> str:
        """构建纯文本邮件正文。"""
        action_text = "登录" if purpose == "login" else "注册"
        return (
            f"WANDER AI 验证码\n\n"
            f"请输入以下验证码以继续{action_text}：\n\n"
            f"{code}\n\n"
            f"该验证码将在 {self._code_expire_minutes} 分钟后失效。\n"
            f"如果不是你本人在尝试{action_text} WANDER AI，请忽略这封邮件。\n\n"
            f"发送至：{email}\n\n"
            f"此致\n"
            f"WANDER AI 团队\n"
        )

    def _build_email_html_body(self, *, email: str, code: str, purpose: AuthPurpose) -> str:
        """构建 HTML 邮件正文。"""
        action_text = "登录" if purpose == "login" else "注册"
        return f"""\
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>WANDER AI 验证码</title>
  </head>
  <body style="margin:0;background:#f6f4ee;padding:32px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#2c2b28;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid rgba(44,43,40,0.06);">
      <tr>
        <td style="padding:48px 40px 40px;">
          <div style="font-size:36px;line-height:1.1;font-weight:700;letter-spacing:-0.04em;color:#2c2b28;">WANDER AI</div>
          <div style="margin-top:32px;font-size:18px;line-height:1.8;color:#2c2b28;">
            输入此临时验证码以继续{action_text}：
          </div>
          <div style="margin-top:20px;padding:22px 28px;border-radius:20px;background:#f4f2ec;font-size:40px;line-height:1.1;letter-spacing:0.18em;font-weight:600;color:#2c2b28;">
            {code}
          </div>
          <div style="margin-top:28px;font-size:16px;line-height:1.9;color:#5f696a;">
            该验证码将在 {self._code_expire_minutes} 分钟后失效。<br />
            如果不是你本人在尝试{action_text} WANDER AI，请忽略这封邮件。
          </div>
          <div style="margin-top:28px;font-size:14px;line-height:1.8;color:#7a8c8f;">
            发送至：{email}
          </div>
          <div style="margin-top:36px;font-size:16px;line-height:1.9;color:#2c2b28;">
            谨致问候<br />
            WANDER AI 团队
          </div>
        </td>
      </tr>
      <tr>
        <td style="padding:0 40px 36px;">
          <div style="height:1px;background:rgba(44,43,40,0.08);"></div>
          <div style="padding-top:20px;font-size:14px;line-height:1.8;color:#8b938f;">
            这是一封系统邮件，请勿直接回复。
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    def _send_email(self, *, email: str, code: str, purpose: AuthPurpose) -> None:
        if self._smtp_settings is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SMTP 未配置，暂时无法发送验证码",
            )

        message = EmailMessage()
        message["From"] = self._smtp_settings.from_email
        message["To"] = email
        message["Subject"] = self._build_email_subject(code)
        message.set_content(
            self._build_email_text_body(email=email, code=code, purpose=purpose),
            subtype="plain",
            charset="utf-8",
        )
        message.add_alternative(
            self._build_email_html_body(email=email, code=code, purpose=purpose),
            subtype="html",
            charset="utf-8",
        )

        try:
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
        except (OSError, smtplib.SMTPException) as exc:
            self._raise_smtp_failure(exc)

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
