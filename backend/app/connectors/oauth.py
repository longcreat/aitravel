"""MCP OAuth 2.1 客户端：发现、动态注册、授权码与 token 刷新。

实现遵循 MCP authorization spec 2025-06-18：
- RFC 9728 (Protected Resource Metadata)
- RFC 8414 (Authorization Server Metadata)
- RFC 7591 (Dynamic Client Registration)
- RFC 7636 (PKCE)
- RFC 8707 (Resource Indicators)
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx


logger = logging.getLogger(__name__)


_DISCOVERY_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_TOKEN_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass
class ProtectedResourceMetadata:
    """RFC 9728 Protected Resource Metadata 子集。"""

    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str]


@dataclass
class AuthorizationServerMetadata:
    """RFC 8414 Authorization Server Metadata 子集。"""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    code_challenge_methods_supported: list[str]
    grant_types_supported: list[str]
    scopes_supported: list[str]


@dataclass
class RegisteredClient:
    """RFC 7591 Dynamic Client Registration 响应中我们关心的字段。"""

    client_id: str
    client_secret: str | None
    token_endpoint_auth_method: str | None


@dataclass
class TokenResponse:
    """OAuth token 端点响应。"""

    access_token: str
    refresh_token: str | None
    token_type: str
    scope: str | None
    expires_in: int | None

    def expires_at_iso(self) -> str | None:
        """计算 access token 的过期时间。"""
        if self.expires_in is None:
            return None
        # 留 60 秒安全边界，避免临界过期
        delta = max(int(self.expires_in) - 60, 0)
        return (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat()


def generate_pkce() -> tuple[str, str]:
    """生成 RFC 7636 (S256) PKCE verifier/challenge。"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    """生成 OAuth state（同时承担 CSRF 防御与服务端会话查找的索引）。"""
    return secrets.token_urlsafe(24)


def canonical_resource_uri(mcp_server_url: str) -> str:
    """按 RFC 8707 / MCP spec 规范化 MCP server canonical URI。"""
    parsed = urlparse(mcp_server_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"非法的 MCP server URL: {mcp_server_url}")
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    # 去掉单个尾部斜杠（MCP spec 推荐）
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]
    rebuilt = f"{scheme}://{netloc}{path}"
    return rebuilt.rstrip("/") if rebuilt.endswith("/") and rebuilt.count("/") <= 3 else rebuilt


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def _split_resource_origin(mcp_server_url: str) -> tuple[str, str]:
    """返回 (origin, path) 二元组，用于拼接 well-known URL。"""
    parsed = urlparse(mcp_server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, parsed.path or ""


async def discover_protected_resource(
    mcp_server_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> ProtectedResourceMetadata:
    """读取 MCP server 的 RFC 9728 protected resource metadata。

    优先尝试 path 维度的发现端点，再回落到 root；这是 spec 允许的两种放置方式。
    """

    async def _try(client_inner: httpx.AsyncClient) -> ProtectedResourceMetadata:
        origin, path = _split_resource_origin(mcp_server_url)
        clean_path = path.rstrip("/")
        candidates: list[str] = []
        if clean_path:
            candidates.append(f"{origin}/.well-known/oauth-protected-resource{clean_path}")
        candidates.append(f"{origin}/.well-known/oauth-protected-resource")

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                data = await _fetch_json(client_inner, candidate)
                return ProtectedResourceMetadata(
                    resource=str(data.get("resource") or canonical_resource_uri(mcp_server_url)),
                    authorization_servers=[str(value) for value in data.get("authorization_servers", []) if value],
                    scopes_supported=[str(value) for value in data.get("scopes_supported", []) if value],
                )
            except httpx.HTTPError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("无法获取 protected resource metadata")

    if client is not None:
        return await _try(client)
    async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT, follow_redirects=True) as owned:
        return await _try(owned)


async def discover_authorization_server(
    authorization_server: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> AuthorizationServerMetadata:
    """读取授权服务器的 RFC 8414 metadata。"""

    async def _try(client_inner: httpx.AsyncClient) -> AuthorizationServerMetadata:
        # Spec 同时允许 .well-known/oauth-authorization-server 和 openid-configuration
        origin, path = _split_resource_origin(authorization_server)
        path = path.rstrip("/")
        candidates: list[str] = []
        if path:
            candidates.extend(
                [
                    f"{origin}/.well-known/oauth-authorization-server{path}",
                    f"{origin}{path}/.well-known/oauth-authorization-server",
                    f"{origin}{path}/.well-known/openid-configuration",
                ]
            )
        candidates.extend(
            [
                f"{origin}/.well-known/oauth-authorization-server",
                f"{origin}/.well-known/openid-configuration",
            ]
        )

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                data = await _fetch_json(client_inner, candidate)
                return AuthorizationServerMetadata(
                    issuer=str(data.get("issuer") or authorization_server),
                    authorization_endpoint=str(data["authorization_endpoint"]),
                    token_endpoint=str(data["token_endpoint"]),
                    registration_endpoint=str(data["registration_endpoint"]) if data.get("registration_endpoint") else None,
                    code_challenge_methods_supported=[
                        str(value) for value in data.get("code_challenge_methods_supported", []) if value
                    ],
                    grant_types_supported=[
                        str(value) for value in data.get("grant_types_supported", []) if value
                    ],
                    scopes_supported=[str(value) for value in data.get("scopes_supported", []) if value],
                )
            except (httpx.HTTPError, KeyError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("无法获取 authorization server metadata")

    if client is not None:
        return await _try(client)
    async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT, follow_redirects=True) as owned:
        return await _try(owned)


async def register_client(
    metadata: AuthorizationServerMetadata,
    *,
    redirect_uri: str,
    client_name: str,
    client_uri: str | None = None,
    logo_uri: str | None = None,
    scope: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> RegisteredClient:
    """RFC 7591 Dynamic Client Registration。"""
    if not metadata.registration_endpoint:
        raise RuntimeError(
            "授权服务器未提供 dynamic client registration 端点，"
            "请联系该服务提供方提供 client_id/secret 或改用支持 DCR 的 MCP server"
        )

    payload: dict[str, Any] = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    if client_uri:
        payload["client_uri"] = client_uri
    if logo_uri:
        payload["logo_uri"] = logo_uri
    if scope:
        payload["scope"] = scope

    async def _send(client_inner: httpx.AsyncClient) -> RegisteredClient:
        response = await client_inner.post(
            metadata.registration_endpoint,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        body = response.json()
        return RegisteredClient(
            client_id=str(body["client_id"]),
            client_secret=str(body["client_secret"]) if body.get("client_secret") else None,
            token_endpoint_auth_method=str(body["token_endpoint_auth_method"]) if body.get("token_endpoint_auth_method") else None,
        )

    if client is not None:
        return await _send(client)
    async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT, follow_redirects=True) as owned:
        return await _send(owned)


def build_authorize_url(
    metadata: AuthorizationServerMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    resource: str,
    scope: str | None,
) -> str:
    """拼装授权请求 URL（含 PKCE 与 RFC 8707 resource）。"""
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": resource,
    }
    if scope:
        params["scope"] = scope
    delimiter = "&" if "?" in metadata.authorization_endpoint else "?"
    return f"{metadata.authorization_endpoint}{delimiter}{urlencode(params)}"


async def exchange_code(
    metadata: AuthorizationServerMetadata,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_id: str,
    client_secret: str | None,
    resource: str,
    client: httpx.AsyncClient | None = None,
) -> TokenResponse:
    """RFC 6749 §4.1 + RFC 8707 + PKCE：用 code 交换 token。"""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "resource": resource,
    }
    return await _post_token(metadata, data=data, client_secret=client_secret, client=client)


async def refresh_tokens(
    metadata: AuthorizationServerMetadata,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str | None,
    resource: str,
    scope: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> TokenResponse:
    """用 refresh_token 续 access_token。"""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "resource": resource,
    }
    if scope:
        data["scope"] = scope
    return await _post_token(metadata, data=data, client_secret=client_secret, client=client)


async def _post_token(
    metadata: AuthorizationServerMetadata,
    *,
    data: dict[str, str],
    client_secret: str | None,
    client: httpx.AsyncClient | None = None,
) -> TokenResponse:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    auth = None
    if client_secret:
        # 优先使用 Basic auth（与 client_secret_basic 保持一致）；client_id 已包含在 form 中也不冲突
        auth = (data["client_id"], client_secret)

    async def _send(client_inner: httpx.AsyncClient) -> TokenResponse:
        response = await client_inner.post(
            metadata.token_endpoint,
            data=data,
            headers=headers,
            auth=auth,
        )
        if response.status_code >= 400:
            logger.warning(
                "OAuth token endpoint returned %s: %s",
                response.status_code,
                response.text[:500],
            )
        response.raise_for_status()
        body = response.json()
        return TokenResponse(
            access_token=str(body["access_token"]),
            refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
            token_type=str(body.get("token_type") or "bearer"),
            scope=str(body["scope"]) if body.get("scope") else None,
            expires_in=int(body["expires_in"]) if body.get("expires_in") is not None else None,
        )

    if client is not None:
        return await _send(client)
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT, follow_redirects=True) as owned:
        return await _send(owned)


def select_authorization_server(metadata: ProtectedResourceMetadata) -> str:
    """按 spec 简化策略选择授权服务器：取列表第一个。"""
    if not metadata.authorization_servers:
        raise RuntimeError(
            "MCP server 的 protected resource metadata 未声明任何 authorization_servers"
        )
    return metadata.authorization_servers[0]


def merge_scopes(default: str | None, supported: list[str]) -> str | None:
    """如果管理员配置了 default scope，就用它；否则尽量请求 server 公开的全部 scope。"""
    if default and default.strip():
        return default.strip()
    if supported:
        return " ".join(supported)
    return None


__all__ = [
    "AuthorizationServerMetadata",
    "ProtectedResourceMetadata",
    "RegisteredClient",
    "TokenResponse",
    "build_authorize_url",
    "canonical_resource_uri",
    "discover_authorization_server",
    "discover_protected_resource",
    "exchange_code",
    "generate_pkce",
    "generate_state",
    "merge_scopes",
    "refresh_tokens",
    "register_client",
    "select_authorization_server",
]
