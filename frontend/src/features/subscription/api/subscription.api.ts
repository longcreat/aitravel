import type {
  OrderQueryResponse,
  Package,
  PaymentOrderRequest,
  PaymentOrderResponse,
  SubscriptionStatus,
} from "@/features/subscription/model/subscription.types";
import { http } from "@/shared/lib/http";

export async function fetchPackages(): Promise<Package[]> {
  return http.get<Package[]>("/api/alipay/packages");
}

export async function fetchSubscription(): Promise<SubscriptionStatus> {
  return http.get<SubscriptionStatus>("/api/alipay/subscription");
}

export async function createPaymentOrder(packageId: string): Promise<PaymentOrderResponse> {
  const payload: PaymentOrderRequest = { package_id: packageId };
  return http.post<PaymentOrderResponse>("/api/alipay/pay", payload);
}

export async function queryPaymentOrder(outTradeNo: string): Promise<OrderQueryResponse> {
  return http.post<OrderQueryResponse>("/api/alipay/query", { out_trade_no: outTradeNo });
}

export function checkoutOrderStorageKey(outTradeNo: string): string {
  return `wander:checkout-order:${outTradeNo}`;
}

export function saveCheckoutOrder(payment: PaymentOrderResponse): void {
  sessionStorage.setItem(checkoutOrderStorageKey(payment.out_trade_no), JSON.stringify(payment));
}

export function loadCheckoutOrder(outTradeNo: string): PaymentOrderResponse | null {
  const raw = sessionStorage.getItem(checkoutOrderStorageKey(outTradeNo));
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as PaymentOrderResponse;
  } catch {
    return null;
  }
}

/** 依据 /pay 响应拼装隐藏表单，由调用方 append 到 document 后 submit 跳转收银台。 */
export function buildAlipayCheckoutForm(payment: PaymentOrderResponse): HTMLFormElement {
  const form = document.createElement("form");
  form.method = "POST";
  form.action = payment.gateway_url;
  form.acceptCharset = "UTF-8";
  form.style.display = "none";

  const fields: Array<[string, string]> = [
    ["app_id", payment.app_id],
    ["method", payment.method],
    ["charset", payment.charset],
    ["sign_type", payment.sign_type],
    ["timestamp", payment.timestamp],
    ["version", payment.version],
    ["notify_url", payment.notify_url],
    ["return_url", payment.return_url],
    ["biz_content", payment.biz_content],
    ["sign", payment.sign],
  ];

  for (const [name, value] of fields) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }

  return form;
}
