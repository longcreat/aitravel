import { Loader2, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  buildAlipayCheckoutForm,
  createPaymentOrder,
  fetchSubscription,
} from "@/features/subscription/api/subscription.api";
import type { SubscriptionStatus } from "@/features/subscription/model/subscription.types";
import { Button, PageBackButton, useToast } from "@/shared/ui";

export function SubscribePage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [subscription, setSubscription] = useState<SubscriptionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [payingPackage, setPayingPackage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setSubscription(await fetchSubscription());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigate("/profile", { replace: true });
  }

  async function handleBuy(packageId: string) {
    setPayingPackage(packageId);
    try {
      const payment = await createPaymentOrder(packageId);
      const form = buildAlipayCheckoutForm(payment);
      document.body.appendChild(form);
      form.submit();
    } catch (error) {
      const message = error instanceof Error ? error.message : "请稍后重试";
      toast({ title: "下单失败", description: message, variant: "destructive" });
      setPayingPackage(null);
    }
  }

  const freeLeft = subscription ? Math.max(0, subscription.daily_free_limit - subscription.free_used) : 0;
  const totalLeft = (subscription?.remain_count ?? 0) + freeLeft;

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
      <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
        <PageBackButton ariaLabel="back-subscribe" onClick={handleBack} />
      </div>

      <section className="px-6 pt-4 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#f6efe0]">
          <Zap className="h-7 w-7 text-[#d4704e]" />
        </div>
        <h1 className="mt-4 text-[22px] font-bold tracking-[-0.02em] text-ink">订阅次数包</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          每日 10 次免费对话，超出后可购买次数包长期使用
        </p>
        {subscription ? (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            剩余可用 <span className="font-semibold text-ink">{totalLeft}</span> 次
            <span className="mx-1">·</span>
            今日免费 {freeLeft} 次 / 已购 {subscription.remain_count} 次
          </p>
        ) : null}
      </section>

      <section className="flex-1 px-4 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-sm text-[#809b9f]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            读取订阅状态…
          </div>
        ) : null}

        {error ? (
          <div className="rounded-2xl bg-white p-8 text-center shadow-sm">
            <p className="text-sm text-[#809b9f]">订阅状态加载失败，请稍后重试</p>
            <Button className="mt-4 rounded-full" onClick={() => void refresh()}>
              重试
            </Button>
          </div>
        ) : null}

        {!loading && !error ? (
          <div className="space-y-4">
            {subscription?.packages.map((pkg) => (
              <div
                key={pkg.id}
                className="rounded-2xl border border-border bg-white p-5 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-[#d4704e]" />
                    <h3 className="text-[16px] font-semibold text-ink">{pkg.name}</h3>
                  </div>
                  <span className="text-[22px] font-bold text-[#d4704e]">¥{pkg.price}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{pkg.quota} 次 AI 对话额度，长期有效</p>
                <Button
                  className="mt-4 w-full rounded-full"
                  disabled={payingPackage !== null}
                  onClick={() => void handleBuy(pkg.id)}
                >
                  {payingPackage === pkg.id ? "跳转收银台..." : "立即购买"}
                </Button>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
