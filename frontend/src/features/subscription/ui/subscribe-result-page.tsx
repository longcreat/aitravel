import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { queryPaymentOrder } from "@/features/subscription/api/subscription.api";
import { Button, PageBackButton } from "@/shared/ui";

const POLL_INTERVAL_MS = 2000;
const MAX_ATTEMPTS = 10;

type ResultStatus = "loading" | "paid" | "pending" | "failed" | "missing";

export function SubscribeResultPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const outTradeNo = searchParams.get("out_trade_no") ?? "";
  const [status, setStatus] = useState<ResultStatus>(outTradeNo ? "loading" : "missing");
  const [remainCount, setRemainCount] = useState(0);
  const [tradeNo, setTradeNo] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const runIdRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    runIdRef.current += 1;
    const runId = runIdRef.current;
    setStatus("loading");
    setRemainCount(0);
    setTradeNo(null);
    let attempts = 0;

    const tick = async () => {
      attempts += 1;
      try {
        const order = await queryPaymentOrder(outTradeNo);
        if (runId !== runIdRef.current) {
          return;
        }
        if (order.paid) {
          setRemainCount(order.remain_count);
          setTradeNo(order.trade_no);
          setStatus("paid");
          return;
        }
        if (order.order_status !== "PENDING") {
          setStatus("failed");
          return;
        }
      } catch {
        if (runId !== runIdRef.current) {
          return;
        }
        setStatus("failed");
        return;
      }
      if (attempts >= MAX_ATTEMPTS) {
        setStatus("pending");
        return;
      }
      timerRef.current = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };

    void tick();
  }, [outTradeNo, stopPolling]);

  useEffect(() => {
    if (!outTradeNo) {
      return;
    }
    startPolling();
    return () => {
      stopPolling();
      runIdRef.current += 1;
    };
  }, [outTradeNo, startPolling, stopPolling]);

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
      <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
        <PageBackButton ariaLabel="back-subscribe-result" onClick={() => navigate("/profile/subscribe")} />
        <h1 className="flex-1 pr-14 text-center text-[17px] font-semibold text-ink">支付结果</h1>
      </div>

      <section className="flex flex-1 flex-col items-center justify-center px-8 pb-16 text-center">
        {status === "loading" && (
          <div className="flex flex-col items-center">
            <Loader2 className="h-12 w-12 animate-spin text-[#d4704e]" />
            <p className="mt-4 text-sm text-muted-foreground">正在确认支付结果…</p>
          </div>
        )}

        {status === "paid" && (
          <>
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-50">
              <CheckCircle2 className="h-10 w-10 text-emerald-500" />
            </div>
            <h2 className="mt-5 text-[20px] font-bold tracking-[-0.02em] text-ink">支付成功</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              已到账，可用次数 <span className="font-semibold text-ink">{remainCount}</span> 次
            </p>
            {tradeNo && (
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                支付宝交易号 <span className="font-mono">{tradeNo}</span>
              </p>
            )}
            <div className="mt-8 w-full max-w-[280px] space-y-3">
              <Button className="w-full rounded-full" onClick={() => navigate("/chat")}>
                继续对话
              </Button>
              <Button variant="ghost" className="w-full rounded-full" onClick={() => navigate("/profile")}>
                返回个人中心
              </Button>
            </div>
          </>
        )}

        {status === "pending" && (
          <>
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-50">
              <Clock className="h-10 w-10 text-amber-500" />
            </div>
            <h2 className="mt-5 text-[20px] font-bold tracking-[-0.02em] text-ink">支付处理中</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              款项可能尚未到账，请稍后在个人中心确认到账情况
            </p>
            <div className="mt-8 w-full max-w-[280px] space-y-3">
              <Button className="w-full rounded-full" onClick={() => navigate("/profile")}>
                查看我的次数
              </Button>
              <Button variant="ghost" className="w-full rounded-full" onClick={() => navigate("/profile/subscribe")}>
                重新支付
              </Button>
            </div>
          </>
        )}

        {status === "failed" && (
          <>
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-rose-50">
              <XCircle className="h-10 w-10 text-rose-400" />
            </div>
            <h2 className="mt-5 text-[20px] font-bold tracking-[-0.02em] text-ink">查询失败</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">订单状态查询失败，请重试或到订阅页重新下单</p>
            <div className="mt-8 w-full max-w-[280px] space-y-3">
              <Button className="w-full rounded-full" onClick={() => void startPolling()}>
                重试
              </Button>
              <Button variant="ghost" className="w-full rounded-full" onClick={() => navigate("/profile/subscribe")}>
                返回订阅页
              </Button>
            </div>
          </>
        )}

        {status === "missing" && (
          <>
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-50">
              <XCircle className="h-10 w-10 text-amber-500" />
            </div>
            <h2 className="mt-5 text-[20px] font-bold tracking-[-0.02em] text-ink">参数缺失</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">缺少订单号，无法确认支付结果</p>
            <Button className="mt-8 w-full max-w-[280px] rounded-full" onClick={() => navigate("/profile/subscribe")}>
              返回订阅页
            </Button>
          </>
        )}
      </section>
    </div>
  );
}
