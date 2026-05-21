"""Connector OAuth API。"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_connector_service, get_current_user
from app.connectors.service import ConnectorAuthorizationError, ConnectorService
from app.schemas.auth import AuthUser
from app.schemas.connectors import (
    ConnectorState,
    ListConnectorsResponse,
    StartAuthorizationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("", response_model=ListConnectorsResponse)
async def list_connectors(
    current_user: AuthUser = Depends(get_current_user),
    service: ConnectorService = Depends(get_connector_service),
) -> ListConnectorsResponse:
    """返回当前用户视角下可授权的应用列表。"""
    connectors = service.list_for_user(current_user.id)
    return ListConnectorsResponse(connectors=connectors)


@router.post("/{connector_id}/authorize", response_model=StartAuthorizationResponse)
async def start_authorization(
    connector_id: str,
    current_user: AuthUser = Depends(get_current_user),
    service: ConnectorService = Depends(get_connector_service),
) -> StartAuthorizationResponse:
    """生成浏览器需要打开的授权 URL。"""
    try:
        return await service.start_authorization(current_user.id, connector_id)
    except ConnectorAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{connector_id}", response_model=ConnectorState)
async def disconnect_connector(
    connector_id: str,
    current_user: AuthUser = Depends(get_current_user),
    service: ConnectorService = Depends(get_connector_service),
) -> ConnectorState:
    """断开当前用户对该应用的授权。"""
    try:
        return service.disconnect(current_user.id, connector_id)
    except ConnectorAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/oauth/callback")
async def oauth_callback(
    state: str = Query(..., min_length=8),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    service: ConnectorService = Depends(get_connector_service),
) -> RedirectResponse:
    """OAuth 授权回调端点。

    成功 / 失败都把用户重定向回前端的 connectors 页面，并附上结果参数。
    """
    error_payload = error or None
    if error_description:
        error_payload = f"{error or 'oauth_error'}: {error_description}"

    try:
        connector_state, redirect_after = await service.complete_authorization(
            state=state,
            code=code,
            error=error_payload,
        )
    except ConnectorAuthorizationError as exc:
        params = {
            "connector_status": "error",
            "connector_error": str(exc),
        }
        return RedirectResponse(url=_append_query("/", params))

    params: dict[str, str] = {
        "connector_id": connector_state.id,
        "connector_status": connector_state.status,
    }
    if connector_state.last_error and connector_state.status != "connected":
        params["connector_error"] = connector_state.last_error
    return RedirectResponse(url=_append_query(redirect_after, params))


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    delimiter = "&" if "?" in url else "?"
    return f"{url}{delimiter}{urlencode(params)}"
