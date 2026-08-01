"""支付服务：套餐定义、建单、notify 校验、扣次。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from app.payment.store import DAILY_FREE_LIMIT, PaymentSQLiteStore

_LOGGER = logging.getLogger(__name__)

PACKAGES: dict[str, dict[str, str | int]] = {
    "trial": {"name": "体验包", "price": "9.90", "quota": 50},
    "standard": {"name": "标准包", "price": "19.90", "quota": 150},
    "unlimited": {"name": "畅玩包", "price": "39.90", "quota": 500},
}


class QuotaExhaustedError(Exception):
    """免费与购买额度均已用尽。"""


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class PaymentService:
    def __init__(self, sqlite_db_path: Path, store_cls: type[PaymentSQLiteStore] = PaymentSQLiteStore) -> None:
        self._store = store_cls(sqlite_db_path)

    def list_packages(self) -> list[dict[str, str | int]]:
        return [
            {"id": package_id, **package}
            for package_id, package in PACKAGES.items()
        ]

    def create_payment_order(self, *, user_id: str, package_id: str) -> str:
        package = PACKAGES.get(package_id)
        if package is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="套餐不存在")
        out_trade_no = uuid4().hex
        self._store.create_order(
            out_trade_no=out_trade_no,
            user_id=user_id,
            package_id=package_id,
            amount=str(package["price"]),
            quota=int(package["quota"]),
        )
        return out_trade_no

    def get_subscription(self, user_id: str) -> dict:
        quota = self._store.get_quota(user_id) or {"remain_count": 0, "free_date": "", "free_used": 0}
        today = _today_utc()
        free_used = quota["free_used"] if quota["free_date"] == today else 0
        return {
            "daily_free_limit": DAILY_FREE_LIMIT,
            "free_used": free_used,
            "remain_count": int(quota["remain_count"]),
            "packages": self.list_packages(),
        }

    def get_order_amount(self, out_trade_no: str) -> str | None:
        """返回订单金额（供支付表单回填），订单不存在返回 None。"""
        order = self._store.get_order(out_trade_no)
        return str(order["amount"]) if order is not None else None

    def get_order(self, out_trade_no: str) -> dict | None:
        """返回订单信息（供支付结果查询），订单不存在返回 None。"""
        return self._store.get_order(out_trade_no)

    def consume(self, user_id: str) -> tuple[int, int]:
        """消费 1 次；额度不足抛 QuotaExhaustedError。

        返回 (更新后的 free_used, 更新后的 remain_count)。
        """
        ok, free_used, remain = self._store.consume_quota(user_id, _today_utc())
        if not ok:
            raise QuotaExhaustedError("今日免费次数已用完，请订阅次数包后继续")
        return free_used, remain

    def handle_notify(self, data: dict[str, str], sign: str | None) -> bool:
        """notify 业务校验：验签 → app_id → 订单 → 金额 → 幂等 → 置 PAID + 加次数。"""
        if not sign:
            return False
        if not self._verify_sign(data, sign):
            _LOGGER.warning("Invalid alipay signature for trade %s", data.get("out_trade_no"))
            return False

        try:
            from app.api.alipay_payment import expected_alipay_app_id
        except ImportError:
            _LOGGER.warning("alipay module not ready, rejecting notify (app_id check)")
            return False

        if data.get("app_id") != expected_alipay_app_id():
            _LOGGER.warning("Unexpected app_id in notify: %s", data.get("app_id"))
            return False

        if data.get("trade_status") not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return True

        out_trade_no = data.get("out_trade_no", "")
        order = self._store.get_order(out_trade_no)
        if order is None:
            _LOGGER.warning("Order not found: %s", out_trade_no)
            return False
        if float(data.get("total_amount", "0")) != float(order["amount"]):
            _LOGGER.warning("Amount mismatch for %s", out_trade_no)
            return False

        if self._store.mark_paid_and_grant(out_trade_no, int(order["quota"])):
            _LOGGER.info("Payment success and quota granted: %s", out_trade_no)
        return True

    def _verify_sign(self, data: dict[str, str], sign: str) -> bool:
        try:
            from app.api.alipay_payment import verify_alipay_signature
        except ImportError:
            _LOGGER.exception("alipay module not ready, rejecting notify")
            return False
        return verify_alipay_signature(data, sign)
