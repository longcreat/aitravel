"""支付宝支付 API 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa

from app.api import deps
from app.main import create_app

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_CONFIG_PATH = _PROJECT_ROOT / ".alipay-sandbox.json"


class _NoopAgentService:
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def runtime_snapshot(self) -> dict:
        return {"ready": False, "mcp_connected_servers": [], "mcp_errors": [], "local_tools": [], "mcp_tools": []}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client: TestClient) -> str:
    send = client.post("/api/auth/send-code", json={"email": "demo@example.com", "purpose": "register"})
    assert send.status_code == 200
    verify = client.post(
        "/api/auth/verify-code",
        json={"email": "demo@example.com", "code": "123456", "purpose": "register"},
    )
    assert verify.status_code == 200
    return verify.json()["access_token"]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("CHAT_SQLITE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-alipay-api-0123456789")
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "demo")
    monkeypatch.setenv("SMTP_PASSWORD", "demo")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.setattr("app.main.get_agent_service", lambda: _NoopAgentService())
    monkeypatch.setattr("app.auth.service.secrets.randbelow", lambda _limit: 123456)
    monkeypatch.setattr("app.auth.service.AuthService._send_email", lambda self, **_kwargs: None)
    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    for dependency in (deps.get_auth_service, deps.get_agent_service, deps.get_payment_service):
        dependency.cache_clear()


def test_packages_public(client: TestClient) -> None:
    response = client.get("/api/alipay/packages")
    assert response.status_code == 200
    packages = response.json()
    assert len(packages) == 3
    assert {package["id"]: package["price"] for package in packages} == {
        "trial": "9.90",
        "standard": "19.90",
        "unlimited": "39.90",
    }


def test_subscription_requires_auth(client: TestClient) -> None:
    response = client.get("/api/alipay/subscription")
    assert response.status_code == 401


def test_subscription_authed_shape(client: TestClient) -> None:
    token = _register_and_login(client)
    response = client.get("/api/alipay/subscription", headers=_auth(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["daily_free_limit"] == 10
    assert payload["free_used"] == 0
    assert payload["remain_count"] == 0
    assert {package["id"] for package in payload["packages"]} == {"trial", "standard", "unlimited"}


def test_pay_requires_auth(client: TestClient) -> None:
    response = client.post("/api/alipay/pay", json={"package_id": "trial"})
    assert response.status_code == 401


def test_pay_authed_valid_package(client: TestClient) -> None:
    token = _register_and_login(client)
    response = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["out_trade_no"]
    assert payload["package"] == "trial"
    assert payload["total_amount"] == "9.90"
    assert payload["subject"] == "WANDER AI 对话次数包"
    assert payload["sign"]
    assert payload["method"] == "alipay.trade.page.pay"
    assert payload["sign_type"] == "RSA2"
    assert payload["charset"] == "utf-8"
    assert payload["version"] == "1.0"
    assert payload["gateway_url"] == "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    assert payload["notify_url"] == "https://aitravel.aigoway.tech/api/alipay/notify"
    assert payload["return_url"] == "https://aitravel.aigoway.tech/api/alipay/return"

    biz_content = json.loads(payload["biz_content"])
    assert biz_content["out_trade_no"] == payload["out_trade_no"]
    assert biz_content["total_amount"] == "9.90"
    assert biz_content["product_code"] == "FAST_INSTANT_TRADE_PAY"

    form_fields = {
        key: payload[key]
        for key in (
            "app_id",
            "method",
            "charset",
            "sign_type",
            "timestamp",
            "version",
            "notify_url",
            "return_url",
            "biz_content",
        )
    }
    sandbox_config = json.loads(_SANDBOX_CONFIG_PATH.read_text(encoding="utf-8"))
    assert verify_with_rsa(
        sandbox_config["appPublicKey"],
        get_sign_content(form_fields).encode("utf-8"),
        payload["sign"],
    )


def test_pay_rejects_unknown_package(client: TestClient) -> None:
    token = _register_and_login(client)
    response = client.post("/api/alipay/pay", json={"package_id": "nope"}, headers=_auth(token))
    assert response.status_code == 400


def test_notify_without_sign_returns_failure(client: TestClient) -> None:
    response = client.post("/api/alipay/notify", data={"out_trade_no": "x"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "failure"


def test_notify_garbage_sign_returns_failure(client: TestClient) -> None:
    response = client.post(
        "/api/alipay/notify",
        data={"out_trade_no": "x", "app_id": "1111111111111111", "sign": "garbage"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "failure"


def test_return_echoes_out_trade_no(client: TestClient) -> None:
    response = client.get("/api/alipay/return", params={"out_trade_no": "abc123"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["out_trade_no"] == "abc123"
    assert payload["paid"] is False


def test_old_alipay_prefix_removed(client: TestClient) -> None:
    assert client.post("/alipay/pay", json={}).status_code == 404
