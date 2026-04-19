"""MCP 连接配置解析与校验。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class StdioConnection(BaseModel):
    """`stdio` 传输配置。"""

    transport: Literal["stdio"]
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class HttpConnection(BaseModel):
    """HTTP/SSE/streamable_http 传输配置。"""

    transport: Literal["http", "streamable_http", "sse"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


ConnectionAdapter = TypeAdapter(StdioConnection | HttpConnection)


def _substitute_env_value(value: Any) -> Any:
    """递归替换 `${ENV_NAME}` 占位符。"""
    if isinstance(value, dict):
        return {k: _substitute_env_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_value(item) for item in value]
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            env_val = os.getenv(env_name)
            if env_val is None:
                raise ValueError(f"Missing environment variable: {env_name}")
            return env_val

        return _ENV_PATTERN.sub(_replace, value)
    return value


def _normalize_transport(connection: dict[str, Any]) -> dict[str, Any]:
    """统一 transport 字段，兼容 `http` 别名。"""
    payload = dict(connection)
    if payload.get("transport") == "http":
        payload["transport"] = "streamable_http"
    return payload


def load_mcp_connections(config_path: Path) -> dict[str, dict[str, Any]]:
    """读取并校验 MCP 连接配置文件。

    Args:
        config_path: 配置文件路径（JSON 格式）。

    Returns:
        dict[str, dict[str, Any]]: 标准化后的连接配置映射。
    """
    if not config_path.exists():
        return {}

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("MCP config must be a JSON object of {serverName: connection}")

    validated: dict[str, dict[str, Any]] = {}
    for server_name, server_cfg in raw.items():
        if not isinstance(server_name, str) or not isinstance(server_cfg, dict):
            raise ValueError(f"Invalid MCP server entry: {server_name}")

        # 先做环境变量替换，再走 pydantic 校验，确保缺失变量能尽早暴露。
        substituted = _substitute_env_value(server_cfg)
        parsed = ConnectionAdapter.validate_python(substituted)
        payload = parsed.model_dump(exclude_none=True)
        validated[server_name] = _normalize_transport(payload)

    return validated
