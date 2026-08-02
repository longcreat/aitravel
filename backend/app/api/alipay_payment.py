"""支付宝网站支付 API（沙箱/正式环境由环境变量控制，缺省回退沙箱配置）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from alipay.aop.api.util.SignatureUtils import get_sign_content, sign_with_rsa2, verify_with_rsa

from app.api.deps import get_current_user, get_payment_service
from app.branding import BRAND_NAME
from app.payment.service import PaymentService
from app.schemas.auth import AuthUser

router = APIRouter(prefix="/api/alipay", tags=["Alipay"])
logger = logging.getLogger(__name__)

_SANDBOX_CONFIG_PATH = Path(__file__).resolve().parents[3] / ".alipay-sandbox.json"


def _load_sandbox_config() -> dict[str, Any]:
    """读取沙箱配置文件；文件缺失或格式非法时返回空字典。"""
    try:
        with open(_SANDBOX_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        logger.warning("Failed to load sandbox config from %s", _SANDBOX_CONFIG_PATH)
        return {}


_SANDBOX_CONFIG = _load_sandbox_config()


def _env(name: str, default: str = "") -> str:
    """读取环境变量，未设置时返回默认值。"""
    return os.getenv(name, default).strip()


def _sandbox_value(key: str) -> str:
    value = _SANDBOX_CONFIG.get(key)
    return str(value) if value else ""


def expected_alipay_app_id() -> str:
    """返回支付宝 app_id：优先环境变量，缺省回退沙箱配置（请求时求值）。"""
    return _env("ALIPAY_APP_ID", _sandbox_value("appId"))


_PRIVATE_KEY_FILE_ENV = "ALIPAY_PRIVATE_KEY_FILE"
_DEFAULT_PRIVATE_KEY_FILE = Path("/app/data/alipay_private_key.pem")


def _alipay_private_key() -> str:
    """应用私钥：优先环境变量，其次私钥文件（容器内 /app/data/alipay_private_key.pem）。"""
    value = _env("ALIPAY_PRIVATE_KEY", _sandbox_value("appPrivatePkcsKey"))
    if value:
        return value
    key_file = Path(os.getenv(_PRIVATE_KEY_FILE_ENV, str(_DEFAULT_PRIVATE_KEY_FILE)))
    try:
        return key_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _require_alipay_config() -> None:
    """校验支付宝配置齐全，缺失时返回 500。"""
    missing = [
        name
        for name, value in (
            ("ALIPAY_APP_ID", expected_alipay_app_id()),
            ("ALIPAY_PRIVATE_KEY", _alipay_private_key()),
            ("ALIPAY_PUBLIC_KEY", _env("ALIPAY_PUBLIC_KEY", _sandbox_value("alipayPublicKey"))),
        )
        if not value
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"支付宝配置缺失: {', '.join(missing)}")


def verify_alipay_signature(data: dict[str, str], sign: str) -> bool:
    """按支付宝规则验签：剔除 sign/sign_type，按 key 排序拼串后 RSA2 验签。"""
    public_key = _env("ALIPAY_PUBLIC_KEY", _sandbox_value("alipayPublicKey"))
    if not public_key:
        return False
    payload = {key: value for key, value in data.items() if key not in ("sign", "sign_type")}
    content = get_sign_content(payload)
    try:
        return bool(verify_with_rsa(public_key, content.encode("utf-8"), sign))
    except Exception:  # noqa: BLE001 - 验签失败统一按 False 处理
        logger.warning("Alipay signature verify failed for trade %s", data.get("out_trade_no"))
        return False


class PayRequest(BaseModel):
    package_id: str


class QueryRequest(BaseModel):
    out_trade_no: str


@router.post("/pay")
async def create_payment(
    req: PayRequest,
    current_user: AuthUser = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
) -> dict[str, Any]:
    """创建订单并返回支付宝网站支付表单字段（前端拼装表单跳转收银台）。"""
    _require_alipay_config()
    out_trade_no = payment_service.create_payment_order(user_id=current_user.id, package_id=req.package_id)
    amount = payment_service.get_order_amount(out_trade_no)
    subject = f"{BRAND_NAME} Quota Pack"
    notify_url = _env("ALIPAY_NOTIFY_URL", "https://aitravel.aigoway.tech/api/alipay/notify")
    return_url = _env("ALIPAY_RETURN_URL", "https://aitravel.aigoway.tech/api/alipay/return")
    biz_content = json.dumps(
        {
            "out_trade_no": out_trade_no,
            "total_amount": amount,
            "subject": subject,
            "product_code": "FAST_INSTANT_TRADE_PAY",
        },
        ensure_ascii=False,
    )
    params = {
        "app_id": expected_alipay_app_id(),
        "method": "alipay.trade.page.pay",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": notify_url,
        "return_url": return_url,
        "biz_content": biz_content,
    }
    private_key = _alipay_private_key()
    sign = sign_with_rsa2(private_key, get_sign_content(params), "utf-8")

    return {
        "out_trade_no": out_trade_no,
        "package": req.package_id,
        "total_amount": amount,
        "subject": subject,
        "sign": sign,
        "gateway_url": _env("ALIPAY_SERVER_URL", "https://openapi-sandbox.dl.alipaydev.com/gateway.do"),
        **params,
    }


@router.post("/notify", response_class=PlainTextResponse)
async def alipay_notify(
    request: Request,
    payment_service: PaymentService = Depends(get_payment_service),
) -> str:
    """支付宝异步通知：验签 + app_id + 金额 + 幂等 后加次数。"""
    form_data = await request.form()
    data: dict[str, str] = {str(key): str(value) for key, value in form_data.items()}
    ok = payment_service.handle_notify(data, data.get("sign"))
    return "success" if ok else "failure"


@router.post("/query")
async def query_payment(
    req: QueryRequest,
    current_user: AuthUser = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
) -> dict[str, Any]:
    """查询本地订单状态（支付结果页轮询用）。"""
    order = payment_service.get_order(req.out_trade_no)
    if order is None or str(order["user_id"]) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    order_status = str(order["status"])
    return {
        "out_trade_no": req.out_trade_no,
        "order_status": order_status,
        "paid": order_status == "PAID",
        "remain_count": payment_service.get_subscription(current_user.id)["remain_count"],
    }


@router.get("/packages")
async def list_packages(
    payment_service: PaymentService = Depends(get_payment_service),
) -> list[dict[str, str | int]]:
    """返回套餐列表（公开）。"""
    return payment_service.list_packages()


@router.get("/subscription")
async def get_subscription(
    current_user: AuthUser = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
) -> dict[str, Any]:
    """返回当前用户剩余次数与套餐列表。"""
    return payment_service.get_subscription(current_user.id)


@router.get("/return")
async def alipay_return(out_trade_no: str = "") -> RedirectResponse:
    """支付宝支付完成后的浏览器跳回；重定向到前端结果页，状态以 notify/query 为准。"""
    return RedirectResponse(url=f"/profile/subscribe/result?out_trade_no={out_trade_no}", status_code=302)
