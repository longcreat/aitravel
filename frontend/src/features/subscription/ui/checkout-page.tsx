import { Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  buildAlipayCheckoutForm,
  fetchSubscription,
  loadCheckoutOrder,
} from "@/features/subscription/api/subscription.api";
import type { PaymentOrderResponse } from "@/features/subscription/model/subscription.types";
import { Button, PageBackButton, useToast } from "@/shared/ui";

export function CheckoutPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const outTradeNo = searchParams.get("out_trade_no");

  const [payment, setPayment] = useState<PaymentOrderResponse | null>(null);
  const [packageName, setPackageName] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const storagePayment = useMemo(
    () => (outTradeNo ? loadCheckoutOrder(outTradeNo) : null),
    [outTradeNo],
  );

  useEffect(() => {
    if (!outTradeNo || !storagePayment) {
      setMissing(true);
      setLoading(false);
      return;
    }
    setPayment(storagePayment);
    void fetchSubscription()
      .then((subscription) => {
        const pkg = subscription.packages.find((p) => p.id === storagePayment.package);
        setPackageName(pkg?.name ?? "AI 对话次数包");
      })
      .catch(() => {
        setPackageName("AI 对话次数包");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [outTradeNo, storagePayment]);

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigate("/profile/subscribe", { replace: true });
  }

  function handlePay() {
    if (!payment) {
      return;
    }
    setSubmitting(true);
    try {
      const form = buildAlipayCheckoutForm(payment);
      document.body.appendChild(form);
      form.submit();
    } catch (error) {
      const message = error instanceof Error ? error.message : "请稍后重试";
      toast({ title: "支付跳转失败", description: message, variant: "destructive" });
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[#faf9f7]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin text-[#809b9f]" />
        <span className="text-sm text-[#809b9f]">加载订单…</span>
      </div>
    );
  }

  if (missing || !payment) {
    return (
      <div className="flex h-full w-full flex-col bg-[#faf9f7]">
        <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
          <PageBackButton ariaLabel="back-checkout-missing" onClick={handleBack} />
        </div>
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="text-sm leading-6 text-[#809b9f]">订单信息缺失或已过期，请重新下单</p>
          <Button className="mt-4 rounded-full" onClick={handleBack}>
            返回订阅页
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
      <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
        <PageBackButton ariaLabel="back-checkout" onClick={handleBack} />
      </div>

      <section className="px-6 pt-4 text-center">
        <h1 className="text-[22px] font-bold tracking-[-0.02em] text-ink">确认支付</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">请确认订单信息后前往支付宝收银台</p>
      </section>

      <section className="flex-1 px-4 py-6">
        <div className="rounded-2xl border border-border bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">商品</span>
            <span className="text-[16px] font-semibold text-ink">{packageName ?? "AI 对话次数包"}</span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">金额</span>
            <span className="text-[22px] font-bold text-[#d4704e]">¥{payment.total_amount}</span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">订单号</span>
            <span className="font-mono text-xs text-muted-foreground">{payment.out_trade_no}</span>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" />
          将跳转至支付宝安全收银台完成支付
        </div>

        <Button className="mt-5 w-full rounded-full" disabled={submitting} onClick={() => void handlePay()}>
          {submitting ? "跳转收银台..." : "去支付宝支付"}
        </Button>
      </section>
    </div>
  );
}
