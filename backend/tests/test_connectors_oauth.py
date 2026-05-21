"""Connector OAuth helper unit tests."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from app.connectors.oauth import (
    AuthorizationServerMetadata,
    build_authorize_url,
    canonical_resource_uri,
    generate_pkce,
    merge_scopes,
)


def test_pkce_pair_roundtrip() -> None:
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    assert challenge == expected


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        ("https://mcp.example.com/mcp", "https://mcp.example.com/mcp"),
        ("https://MCP.Example.com/mcp/", "https://mcp.example.com/mcp"),
        ("https://mcp.example.com:8443/sse/", "https://mcp.example.com:8443/sse"),
        ("https://mcp.example.com", "https://mcp.example.com"),
    ],
)
def test_canonical_resource_uri_normalizes(input_url: str, expected: str) -> None:
    assert canonical_resource_uri(input_url) == expected


def test_canonical_resource_uri_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        canonical_resource_uri("mcp.example.com")


def test_build_authorize_url_includes_resource_and_pkce() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://auth.example.com",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        registration_endpoint=None,
        code_challenge_methods_supported=["S256"],
        grant_types_supported=["authorization_code"],
        scopes_supported=["read"],
    )
    url = build_authorize_url(
        metadata,
        client_id="abc123",
        redirect_uri="https://app.example.com/cb",
        state="xyz",
        code_challenge="ch",
        resource="https://mcp.example.com/mcp",
        scope="read write",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.example.com"
    assert parsed.path == "/authorize"
    params = parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["abc123"]
    assert params["redirect_uri"] == ["https://app.example.com/cb"]
    assert params["state"] == ["xyz"]
    assert params["code_challenge"] == ["ch"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == ["https://mcp.example.com/mcp"]
    assert params["scope"] == ["read write"]


def test_merge_scopes_prefers_admin_default() -> None:
    assert merge_scopes("read:notes", ["read", "write"]) == "read:notes"


def test_merge_scopes_falls_back_to_supported() -> None:
    assert merge_scopes(None, ["read", "write"]) == "read write"


def test_merge_scopes_returns_none_when_unknown() -> None:
    assert merge_scopes(None, []) is None
