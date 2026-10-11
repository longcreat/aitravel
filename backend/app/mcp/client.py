"""MCP 工具装配层：统一全局 MCP 服务器与用户级 connector 的工具加载。

架构（langchain.mcp + fastmcp，2026-10 重建）
------------------------------------------------
所有 MCP 工具（全局配置的 amap 等 stdio/http 服务器、用户 OAuth 连接的
connector）都经由同一条装配管线：

    server spec → fastmcp Client（可带 per-user auth）→ 单成员 ClientGroup
    → langchain.mcp.MCPAdapter → list_tools() → LangChain 工具

设计决策：
- **单成员 ClientGroup**：保留 `{server}_{tool}` 命名前缀（前端工具显示名与
  健康检查依赖）+ 按服务器隔离的错误边界。
- **每服务器独立 Client**（而非 MCPConfig dict）：用户 connector 的 token
  走 fastmcp 原生 `auth=` 凭证（ bearer token 存在 client 上，符合官方
  per-user authentication 模式），而不是烘焙进静态 headers。
- **并行发现**：多服务器并发 `list_tools`，单个失败不阻塞其他。
- **协议时代**：现有 MCP 服务器均建于 legacy 时代（旧 adapters 只支持
  legacy），默认 `mode="legacy"` 保持行为不变；每服务器可在配置中覆盖。
- 发现完成后即可退出 adapter 上下文：返回的工具持有各自客户端、按调用
  自开会话，无需在 shutdown 时统一关闭连接。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastmcp import Client as FastMCPClient
from fastmcp.client.group import ClientGroup
from langchain.mcp import MCPAdapter

logger = logging.getLogger(__name__)

_DEFAULT_PROTOCOL_MODE = "legacy"
# 单次工具调用超时：MCP 服务器 stdout 被污染（如 amap 打印非 JSON 调试行）时
# 响应行会被解析器丢弃、请求 future 永远等不到结果 —— 没有超时的话整轮对话
# 会无限挂起（前端工具卡片永远转圈）。超时后异常经 ToolErrorMiddleware 变成
# error ToolMessage，模型可重试或换工具作答。
_DEFAULT_TOOL_TIMEOUT_S = 60.0


@dataclass
class MCPToolBundle:
    """MCP 工具加载结果。

    Attributes:
        tools: 可供 Agent 调用的工具列表（名字带 `{server}_` 前缀）。
        connected_servers: 成功连接的 MCP 服务名列表。
        errors: 加载错误列表（字符串形式）。
    """

    tools: list[Any] = field(default_factory=list)
    connected_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ServerSpec:
    """单个 MCP 服务器的装配输入。

    Attributes:
        name: 服务名（决定工具名前缀 `{name}_`）。
        url: streamable HTTP / SSE 服务器地址。
        transport: 显式传输类型；None 时由 URL 推断（/sse 结尾 → sse）。
        auth: fastmcp 凭证（bearer token 字符串或 httpx.Auth）；
            仅 http 类服务器；stdio 服务器用 env 传凭证。
        mode: 协议时代（legacy/modern/auto）；默认 legacy。
        headers: 额外静态请求头（仅无 auth 时使用）。
        command/args/env: stdio 服务器参数。
    """

    name: str
    url: str | None = None
    transport: str | None = None
    auth: Any = None
    mode: str = _DEFAULT_PROTOCOL_MODE
    headers: dict[str, str] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    timeout: float | None = None  # 单次工具调用超时（秒）；None → 默认 60s

    def to_fastmcp_client(self) -> FastMCPClient:
        """按 spec 构建 fastmcp Client（凭证、协议时代与超时都挂在 client 上）。"""
        timeout = self.timeout or _DEFAULT_TOOL_TIMEOUT_S
        if self.command is not None:
            return FastMCPClient(self._stdio_transport(), mode=self.mode, timeout=timeout)
        assert self.url is not None, "http server spec requires url"

        from fastmcp.client.transports import (
            SSETransport,
            StreamableHttpTransport,
        )

        transport_type = self.transport or _infer_transport(self.url)
        headers = self.headers
        if self.auth is not None:
            # 官方 per-user auth 模式：token 挂在 client/transport 上，
            # 由 fastmcp 注入 Authorization 头
            if transport_type == "sse":
                return FastMCPClient(
                    SSETransport(self.url, auth=self.auth), mode=self.mode, timeout=timeout
                )
            return FastMCPClient(
                StreamableHttpTransport(self.url, headers=headers, auth=self.auth),
                mode=self.mode,
                timeout=timeout,
            )
        if transport_type == "sse":
            return FastMCPClient(
                SSETransport(self.url, headers=headers), mode=self.mode, timeout=timeout
            )
        return FastMCPClient(
            StreamableHttpTransport(self.url, headers=headers),
            mode=self.mode,
            timeout=timeout,
        )

    def _stdio_transport(self):
        from fastmcp.client.transports import StdioTransport

        return StdioTransport(command=self.command, args=self.args or [], env=self.env or {})


def _infer_transport(url: str) -> str:
    """SSE 是协议废弃传输，仅对以 /sse 结尾的旧服务器显式声明。"""
    return "sse" if urlparse(url).path.lower().endswith("/sse") else "streamable_http"


async def _discover_one(spec: ServerSpec) -> tuple[str, list[Any] | None, str | None]:
    """装配并发现单个服务器的工具。返回 (name, tools, error)。"""
    try:
        group = ClientGroup({spec.name: spec.to_fastmcp_client()})
        adapter = MCPAdapter(group)
        async with adapter:
            tools = await adapter.list_tools(cache_mode="use")
        return spec.name, tools, None
    except Exception as exc:  # noqa: BLE001 - 单服务器失败不阻塞其他
        logger.warning("Failed to initialize MCP server %s: %s", spec.name, exc)
        return spec.name, None, f"{spec.name}: {exc}"


async def assemble_mcp_tools(specs: list[ServerSpec]) -> MCPToolBundle:
    """并行装配多个 MCP 服务器的工具集合。

    单个服务器失败只记入 errors，不影响其他服务器的工具。
    """
    if not specs:
        return MCPToolBundle()

    results = await asyncio.gather(*(_discover_one(spec) for spec in specs))

    bundle = MCPToolBundle()
    for name, tools, error in results:
        if error is not None or tools is None:
            bundle.errors.append(error or f"{name}: unknown failure")
            continue
        bundle.tools.extend(tools)
        bundle.connected_servers.append(name)
    return bundle


# ---------------------------------------------------------------------------
# 旧入口保留：全局 mcp.servers.json 配置 → ServerSpec
# ---------------------------------------------------------------------------

_ENTRY_KEYS = {"url", "command", "args", "env", "headers", "mode", "transport", "timeout"}


def _entry_to_spec(name: str, connection: dict[str, Any]) -> ServerSpec:
    """把内部连接配置（mcp.servers.json 条目）转换为 ServerSpec。"""
    entry = {key: value for key, value in connection.items() if key in _ENTRY_KEYS}
    transport = entry.get("transport")
    if transport == "http":
        transport = None  # 归一化别名：由 URL 推断 streamable_http
    timeout = entry.get("timeout")
    return ServerSpec(
        name=name,
        url=entry.get("url"),
        transport=transport,
        headers=entry.get("headers"),
        mode=entry.get("mode") or _DEFAULT_PROTOCOL_MODE,
        command=entry.get("command"),
        args=entry.get("args"),
        env=entry.get("env"),
        timeout=float(timeout) if timeout is not None else None,
    )


async def load_mcp_tools(connections: dict[str, dict[str, Any]]) -> MCPToolBundle:
    """基于连接配置初始化 MCP 工具集合（全局 mcp.servers.json 入口）。

    Args:
        connections: 已校验的 MCP 连接配置。

    Returns:
        MCPToolBundle: 包含工具、连接状态与错误信息；单个服务器失败不影响其他。
    """
    specs = [_entry_to_spec(name, connection) for name, connection in connections.items()]
    return await assemble_mcp_tools(specs)
