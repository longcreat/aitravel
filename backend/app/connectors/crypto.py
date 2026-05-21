"""Connector 凭证对称加密。"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _derive_key(secret: str) -> bytes:
    """把任意长度的字符串密钥派生成 AES-256-GCM 所需的 32 字节密钥。"""
    return hashlib.sha256(secret.encode("utf-8")).digest()


@lru_cache
def _key_material() -> bytes:
    """读取 token 加密密钥；缺失时回退到 `JWT_SECRET`。

    生产环境强烈建议显式配置 `MCP_TOKEN_ENC_KEY`，便于独立轮转。
    """
    explicit = os.getenv("MCP_TOKEN_ENC_KEY", "").strip()
    if explicit:
        return _derive_key(explicit)
    fallback = os.getenv("JWT_SECRET", "").strip()
    if not fallback:
        raise RuntimeError(
            "无法初始化 Connector 加密：请设置 MCP_TOKEN_ENC_KEY 或 JWT_SECRET"
        )
    return _derive_key(fallback)


def encrypt_secret(plaintext: str) -> str:
    """加密敏感字符串，返回 base64 文本（含 12 字节 nonce 前缀）。"""
    if not plaintext:
        return ""
    aes = AESGCM(_key_material())
    nonce = os.urandom(12)
    cipher = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + cipher).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    """解密 `encrypt_secret` 产出的密文。"""
    if not token:
        return None
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(raw) <= 12:
        raise ValueError("加密密文格式不正确")
    nonce, cipher = raw[:12], raw[12:]
    plain = AESGCM(_key_material()).decrypt(nonce, cipher, None)
    return plain.decode("utf-8")
