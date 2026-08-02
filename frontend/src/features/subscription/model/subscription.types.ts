export interface Package {
  id: string;
  name: string;
  price: string;
  quota: number;
}

export interface SubscriptionStatus {
  daily_free_limit: number;
  free_used: number;
  remain_count: number;
  packages: Package[];
}

export interface PaymentOrderRequest {
  package_id: string;
}

export interface PaymentOrderResponse {
  out_trade_no: string;
  package: string;
  total_amount: string;
  subject: string;
  sign: string;
  gateway_url: string;
  app_id: string;
  method: string;
  charset: string;
  sign_type: string;
  timestamp: string;
  version: string;
  notify_url: string;
  return_url: string;
  biz_content: string;
}

export type OrderStatus = "PENDING" | "PAID" | "CLOSED" | "REFUNDED";

export interface OrderQueryResponse {
  out_trade_no: string;
  order_status: OrderStatus;
  paid: boolean;
  trade_no: string | null;
  remain_count: number;
}
