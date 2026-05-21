"""Connector OAuth 业务编排。"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.connectors.crypto import decrypt_secret, encrypt_secret
from app.connectors.oauth import (
    AuthorizationServerMetadata,
    TokenResponse,
    build_authorize_url,
    canonical_resource_uri,
    discover_authorization_server,
    discover_protected_resource,
    exchange_code,
    generate_pkce,
    generate_state,
    merge_scopes,
    refresh_tokens,
    register_client,
    select_authorization_server,
)
from app.connectors.registry import ConnectorRegistry
from app.connectors.store import (
    AuthorizationRow,
    ConnectorAuthStore,
    OAuthStateRow,
)
from app.schemas.connectors import (
    ConnectorDefinition,
    ConnectorState,
    StartAuthorizationResponse,
)

logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_in_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class ConnectorAuthorizationError(RuntimeError):
    """对外抛出的 connector 授权异常。"""


class ConnectorService:
    """协调 connector 目录、用户授权状态与 OAuth 流。"""

    def __init__(self, sqlite_db_path: Path) -> None:
        self._registry = ConnectorRegistry.load()
        self._store = ConnectorAuthStore(sqlite_db_path)
        self._redirect_uri = os.getenv(
            "CONNECTOR_REDIRECT_URL",
            "http://localhost:8000/api/connectors/oauth/callback",
        ).strip()
        self._frontend_return_url = os.getenv(
            "CONNECTOR_FRONTEND_RETURN_URL",
            "http://localhost:5173/profile/connectors",
        ).strip()

    # ---- public API ----

    def list_for_user(self, user_id: str) -> list[ConnectorState]:
        """返回该用户视角下的全部 connector 状态。"""
        rows = {row.connector_id: row for row in self._store.list_for_user(user_id)}
        states: list[ConnectorState] = []
        for definition in self._registry.list():
            row = rows.get(definition.id)
            states.append(
                ConnectorState(
                    id=definition.id,
                    display_name=definition.display_name,
                    description=definition.description,
                    icon_url=definition.icon_url,
                    mcp_server_url=definition.mcp_server_url,
                    enabled=definition.enabled,
                    status=row.status if row else "disconnected",  # type: ignore[arg-type]
                    connected_at=row.updated_at if row and row.status == "connected" else None,
                    last_error=row.last_error if row else None,
                )
            )
        return states

    async def start_authorization(self, user_id: str, connector_id: str) -> StartAuthorizationResponse:
        """开启一次授权流程，返回浏览器需要跳转的授权 URL。"""
        definition = self._require_definition(connector_id)
        authorization = self._store.upsert_authorization_record(
            user_id=user_id,
            connector_id=definition.id,
            mcp_server_url=definition.mcp_server_url,
            redirect_uri=self._redirect_uri,
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                metadata, server_metadata = await self._discover_metadata(definition, client=client)
            except Exception as exc:
                self._store.mark_failed(authorization.id, f"发现授权服务器失败：{exc}")
                logger.exception("Failed to discover MCP authorization metadata for %s", connector_id)
                raise ConnectorAuthorizationError(
                    "无法连接到该应用的授权服务，请稍后重试或联系管理员"
                ) from exc

            self._store.update_authorization_server(authorization.id, server_metadata.issuer)

            client_id, client_secret_plain = await self._ensure_oauth_client(
                authorization=authorization,
                definition=definition,
                server_metadata=server_metadata,
                client=client,
            )

        scope = merge_scopes(definition.default_scopes, server_metadata.scopes_supported)
        verifier, challenge = generate_pkce()
        state_value = generate_state()
        resource = canonical_resource_uri(definition.mcp_server_url)

        authorize_url = build_authorize_url(
            server_metadata,
            client_id=client_id,
            redirect_uri=authorization.redirect_uri,
            state=state_value,
            code_challenge=challenge,
            resource=resource,
            scope=scope,
        )

        # 保留 client_secret 以备 token 交换。
        self._store.purge_expired_states()
        self._store.save_oauth_state(
            OAuthStateRow(
                state=state_value,
                user_id=user_id,
                connector_id=connector_id,
                authorization_id=authorization.id,
                code_verifier=verifier,
                redirect_after=self._frontend_return_url,
                expires_at=_expires_in_iso(_STATE_TTL_SECONDS),
                created_at=_utc_now_iso(),
            )
        )

        # 把 plain client_secret 短暂保留到内存？我们在交换 code 阶段会再读 store 拿密文解密。
        del client_secret_plain  # 防止悬挂引用

        return StartAuthorizationResponse(
            authorize_url=authorize_url,
            state=state_value,
            expires_in=_STATE_TTL_SECONDS,
        )

    async def complete_authorization(
        self, *, state: str, code: str | None, error: str | None
    ) -> tuple[ConnectorState, str]:
        """处理 OAuth 回调：换取 token，返回 (connector_state, redirect_url)。"""
        record = self._store.consume_oauth_state(state)
        if record is None:
            raise ConnectorAuthorizationError("授权请求已失效，请重新发起")

        authorization = self._store.get_by_id(record.authorization_id)
        if authorization is None:
            raise ConnectorAuthorizationError("授权记录不存在")
        if authorization.user_id != record.user_id:
            raise ConnectorAuthorizationError("授权请求与用户不匹配")

        if error:
            self._store.mark_failed(authorization.id, f"用户拒绝或授权失败：{error}")
            return await self._build_state_for_redirect(authorization, success=False), record.redirect_after or self._frontend_return_url

        if not code:
            self._store.mark_failed(authorization.id, "授权回调缺少 code")
            raise ConnectorAuthorizationError("授权回调缺少 code")

        definition = self._require_definition(authorization.connector_id)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                _, server_metadata = await self._discover_metadata(definition, client=client)
            except Exception as exc:
                self._store.mark_failed(authorization.id, f"发现授权服务器失败：{exc}")
                raise ConnectorAuthorizationError(
                    "无法连接到该应用的授权服务，请稍后重试"
                ) from exc

            client_secret = decrypt_secret(authorization.client_secret_enc)
            try:
                token = await exchange_code(
                    server_metadata,
                    code=code,
                    redirect_uri=authorization.redirect_uri,
                    code_verifier=record.code_verifier,
                    client_id=authorization.client_id or "",
                    client_secret=client_secret,
                    resource=canonical_resource_uri(definition.mcp_server_url),
                    client=client,
                )
            except httpx.HTTPError as exc:
                self._store.mark_failed(authorization.id, f"token 交换失败：{exc}")
                raise ConnectorAuthorizationError("授权失败，请稍后重试") from exc

        self._save_token_response(authorization.id, token)
        return (
            await self._build_state_for_redirect(self._store.get_by_id(authorization.id), success=True),
            record.redirect_after or self._frontend_return_url,
        )

    def disconnect(self, user_id: str, connector_id: str) -> ConnectorState:
        """断开（撤销）该用户对 connector 的授权。"""
        definition = self._require_definition(connector_id)
        record = self._store.get_for_user(user_id, connector_id)
        if record is not None:
            self._store.mark_revoked(record.id)
        # 重新读取一次，构建对外结果
        refreshed = self._store.get_for_user(user_id, connector_id)
        return self._compose_state(definition, refreshed)

    async def list_user_active_connections(
        self, user_id: str
    ) -> list[tuple[ConnectorDefinition, AuthorizationRow, str]]:
        """返回该用户当前可用的 connector 三元组：(definition, row, access_token)。

        这一步会按需刷新 token；刷新失败的会被标记为 expired 并被排除。
        """
        connections = self._store.list_connected(user_id)
        if not connections:
            return []

        results: list[tuple[ConnectorDefinition, AuthorizationRow, str]] = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for row in connections:
                definition = self._registry.get(row.connector_id)
                if definition is None:
                    continue
                try:
                    access_token = await self._ensure_fresh_token(row, definition, client=client)
                except Exception as exc:
                    logger.warning(
                        "Failed to refresh token for user=%s connector=%s: %s",
                        user_id,
                        row.connector_id,
                        exc,
                    )
                    self._store.mark_failed(row.id, f"刷新 access token 失败：{exc}")
                    continue
                refreshed = self._store.get_by_id(row.id) or row
                results.append((definition, refreshed, access_token))
        return results

    # ---- internals ----

    def _require_definition(self, connector_id: str) -> ConnectorDefinition:
        definition = self._registry.get(connector_id)
        if definition is None:
            raise ConnectorAuthorizationError("应用不存在或已下架")
        return definition

    async def _discover_metadata(
        self,
        definition: ConnectorDefinition,
        *,
        client: httpx.AsyncClient,
    ) -> tuple[Any, AuthorizationServerMetadata]:
        protected = await discover_protected_resource(definition.mcp_server_url, client=client)
        authorization_server = select_authorization_server(protected)
        server_metadata = await discover_authorization_server(authorization_server, client=client)
        return protected, server_metadata

    async def _ensure_oauth_client(
        self,
        *,
        authorization: AuthorizationRow,
        definition: ConnectorDefinition,
        server_metadata: AuthorizationServerMetadata,
        client: httpx.AsyncClient,
    ) -> tuple[str, str | None]:
        """若尚未注册过 OAuth client，则按 RFC 7591 注册一次。"""
        if authorization.client_id:
            secret = decrypt_secret(authorization.client_secret_enc)
            return authorization.client_id, secret

        client_name = f"{definition.display_name} (AI Travel)"
        registered = await register_client(
            server_metadata,
            redirect_uri=authorization.redirect_uri,
            client_name=client_name,
            client_uri=os.getenv("CONNECTOR_CLIENT_URI") or None,
            logo_uri=os.getenv("CONNECTOR_CLIENT_LOGO_URI") or None,
            scope=definition.default_scopes,
            client=client,
        )
        secret_enc = encrypt_secret(registered.client_secret) if registered.client_secret else None
        self._store.update_client_credentials(
            authorization.id,
            authorization_server=server_metadata.issuer,
            client_id=registered.client_id,
            client_secret_enc=secret_enc,
        )
        return registered.client_id, registered.client_secret

    def _save_token_response(self, authorization_id: str, token: TokenResponse) -> None:
        self._store.save_tokens(
            authorization_id,
            access_token_enc=encrypt_secret(token.access_token),
            refresh_token_enc=encrypt_secret(token.refresh_token) if token.refresh_token else None,
            token_type=token.token_type,
            scope=token.scope,
            expires_at=token.expires_at_iso(),
        )

    async def _ensure_fresh_token(
        self,
        row: AuthorizationRow,
        definition: ConnectorDefinition,
        *,
        client: httpx.AsyncClient,
    ) -> str:
        access_token = decrypt_secret(row.access_token_enc)
        if not access_token:
            raise ConnectorAuthorizationError("access token 不存在")

        # 没有 expires_at 的服务（少见）就不刷新，直接用
        if row.expires_at is None:
            return access_token

        try:
            expires_at = datetime.fromisoformat(row.expires_at)
        except ValueError:
            return access_token

        if expires_at - datetime.now(timezone.utc) > timedelta(seconds=30):
            return access_token

        # 尝试 refresh
        refresh_token = decrypt_secret(row.refresh_token_enc)
        if not refresh_token or not row.client_id:
            raise ConnectorAuthorizationError("token 已过期且无法自动刷新")

        _, server_metadata = await self._discover_metadata(definition, client=client)
        token = await refresh_tokens(
            server_metadata,
            refresh_token=refresh_token,
            client_id=row.client_id,
            client_secret=decrypt_secret(row.client_secret_enc),
            resource=canonical_resource_uri(definition.mcp_server_url),
            scope=row.scope,
            client=client,
        )
        self._save_token_response(row.id, token)
        return token.access_token

    def _compose_state(
        self,
        definition: ConnectorDefinition,
        row: AuthorizationRow | None,
    ) -> ConnectorState:
        return ConnectorState(
            id=definition.id,
            display_name=definition.display_name,
            description=definition.description,
            icon_url=definition.icon_url,
            mcp_server_url=definition.mcp_server_url,
            enabled=definition.enabled,
            status=row.status if row else "disconnected",  # type: ignore[arg-type]
            connected_at=row.updated_at if row and row.status == "connected" else None,
            last_error=row.last_error if row else None,
        )

    async def _build_state_for_redirect(
        self,
        row: AuthorizationRow | None,
        *,
        success: bool,
    ) -> ConnectorState:
        if row is None:
            raise ConnectorAuthorizationError("授权记录不存在")
        definition = self._registry.get(row.connector_id)
        if definition is None:
            raise ConnectorAuthorizationError("应用不存在")
        state = self._compose_state(definition, row)
        if not success:
            state.status = row.status  # 保留底层状态（failed / revoked）
        return state
