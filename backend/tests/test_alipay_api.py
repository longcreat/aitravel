"""支付宝支付 API 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alipay.aop.api.util.SignatureUtils import get_sign_content, sign_with_rsa2, verify_with_rsa

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


def _register_and_login(client: TestClient, email: str = "demo@example.com") -> str:
    send = client.post("/api/auth/send-code", json={"email": email, "purpose": "register"})
    assert send.status_code == 200
    verify = client.post(
        "/api/auth/verify-code",
        json={"email": email, "code": "123456", "purpose": "register"},
    )
    assert verify.status_code == 200
    return verify.json()["access_token"]


def _sandbox_config() -> dict:
    return json.loads(_SANDBOX_CONFIG_PATH.read_text(encoding="utf-8"))


def _sign_notify(params: dict[str, str], private_key: str) -> str:
    return sign_with_rsa2(private_key, get_sign_content(params), "utf-8")


def _create_paid_order(monkeypatch: pytest.MonkeyPatch, client: TestClient, token: str) -> str:
    """用沙箱应用私钥签名一个 TRADE_SUCCESS notify 将订单置为 PAID。"""
    pay = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert pay.status_code == 200
    out_trade_no = pay.json()["out_trade_no"]
    sandbox_config = _sandbox_config()
    monkeypatch.setenv("ALIPAY_PUBLIC_KEY", sandbox_config["appPublicKey"])
    params = {
        "app_id": sandbox_config["appId"],
        "out_trade_no": out_trade_no,
        "total_amount": "9.90",
        "trade_status": "TRADE_SUCCESS",
    }
    notify = client.post("/api/alipay/notify", data={**params, "sign": _sign_notify(params, sandbox_config["appPrivatePkcsKey"])})
    assert notify.text == "success"
    return out_trade_no


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
    assert payload["subject"] == "WANDER AI Quota Pack"
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


def test_notify_success_grants_quota_idempotent(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    token = _register_and_login(client)
    pay = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert pay.status_code == 200
    out_trade_no = pay.json()["out_trade_no"]

    sandbox_config = _sandbox_config()
    monkeypatch.setenv("ALIPAY_PUBLIC_KEY", sandbox_config["appPublicKey"])
    params = {
        "app_id": sandbox_config["appId"],
        "out_trade_no": out_trade_no,
        "total_amount": "9.90",
        "trade_status": "TRADE_SUCCESS",
    }
    sign = _sign_notify(params, sandbox_config["appPrivatePkcsKey"])

    notify = client.post("/api/alipay/notify", data={**params, "sign": sign})
    assert notify.status_code == 200
    assert notify.headers["content-type"].startswith("text/plain")
    assert notify.text == "success"

    subscription = client.get("/api/alipay/subscription", headers=_auth(token)).json()
    assert subscription["remain_count"] == 50

    second = client.post("/api/alipay/notify", data={**params, "sign": sign})
    assert second.text == "success"
    subscription = client.get("/api/alipay/subscription", headers=_auth(token)).json()
    assert subscription["remain_count"] == 50


def test_query_requires_auth(client: TestClient) -> None:
    response = client.post("/api/alipay/query", json={"out_trade_no": "x"})
    assert response.status_code == 401


def test_query_unknown_order_404(client: TestClient) -> None:
    token = _register_and_login(client)
    response = client.post("/api/alipay/query", json={"out_trade_no": "no-such-order"}, headers=_auth(token))
    assert response.status_code == 404


def test_query_other_users_order_404(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    token_a = _register_and_login(client)
    out_trade_no = _create_paid_order(monkeypatch, client, token_a)
    token_b = _register_and_login(client, email="other@example.com")
    response = client.post("/api/alipay/query", json={"out_trade_no": out_trade_no}, headers=_auth(token_b))
    assert response.status_code == 404


def test_query_own_paid_order(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    token = _register_and_login(client)
    out_trade_no = _create_paid_order(monkeypatch, client, token)
    response = client.post("/api/alipay/query", json={"out_trade_no": out_trade_no}, headers=_auth(token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["out_trade_no"] == out_trade_no
    assert payload["order_status"] == "PAID"
    assert payload["paid"] is True
    assert payload["remain_count"] == 50


def test_pay_uses_env_app_id_when_set(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("ALIPAY_APP_ID", "9999999999999999")
    token = _register_and_login(client)
    response = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["app_id"] == "9999999999999999"


def test_pay_reads_private_key_from_file(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    monkeypatch.delenv("ALIPAY_PRIVATE_KEY", raising=False)
    sandbox_config = _sandbox_config()
    key_file = tmp_path / "alipay_private_key.pem"
    key_file.write_text(sandbox_config["appPrivatePkcsKey"], encoding="utf-8")
    monkeypatch.setenv("ALIPAY_PRIVATE_KEY_FILE", str(key_file))

    token = _register_and_login(client)
    response = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["sign"]


def test_pay_accepts_pkcs8_private_key_file(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    monkeypatch.delenv("ALIPAY_PRIVATE_KEY", raising=False)
    sandbox_config = _sandbox_config()
    key_file = tmp_path / "alipay_private_key.pem"
    key_file.write_text(sandbox_config["appPrivateKey"], encoding="utf-8")
    monkeypatch.setenv("ALIPAY_PRIVATE_KEY_FILE", str(key_file))

    token = _register_and_login(client)
    response = client.post("/api/alipay/pay", json={"package_id": "trial"}, headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["sign"]


def test_return_redirects_to_result_page(client: TestClient) -> None:
    response = client.get(
        "/api/alipay/return",
        params={"out_trade_no": "abc123"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/profile/subscribe/result?out_trade_no=abc123"


def test_old_alipay_prefix_removed(client: TestClient) -> None:
    assert client.post("/alipay/pay", json={}).status_code == 404
