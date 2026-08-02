import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PaymentOrderResponse,
  SubscriptionStatus,
} from "@/features/subscription/model/subscription.types";
import { CheckoutPage } from "@/features/subscription/ui/checkout-page";
import { saveCheckoutOrder } from "@/features/subscription/api/subscription.api";

const { fetchSubscriptionMock, buildAlipayCheckoutFormMock, toastMock } = vi.hoisted(() => ({
  fetchSubscriptionMock: vi.fn(),
  buildAlipayCheckoutFormMock: vi.fn(),
  toastMock: vi.fn(),
}));

vi.mock("@/features/subscription/api/subscription.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/subscription/api/subscription.api")>();
  return {
    ...actual,
    fetchSubscription: fetchSubscriptionMock,
    buildAlipayCheckoutForm: buildAlipayCheckoutFormMock,
  };
});

vi.mock("@/shared/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/shared/ui")>();
  return {
    ...actual,
    useToast: () => ({ toast: toastMock }),
  };
});

const subscription: SubscriptionStatus = {
  daily_free_limit: 10,
  free_used: 0,
  remain_count: 0,
  packages: [
    { id: "trial", name: "体验包", price: "9.90", quota: 50 },
    { id: "standard", name: "标准包", price: "19.90", quota: 150 },
  ],
};

const payment: PaymentOrderResponse = {
  out_trade_no: "order-1",
  package: "standard",
  total_amount: "19.90",
  subject: "WANDER AI 对话次数包",
  sign: "fake-sign",
  gateway_url: "https://openapi-sandbox.dl.alipaydev.com/gateway.do",
  app_id: "app-1",
  method: "alipay.trade.page.pay",
  charset: "utf-8",
  sign_type: "RSA2",
  timestamp: "2026-08-01 12:00:00",
  version: "1.0",
  notify_url: "https://example.com/notify",
  return_url: "https://example.com/profile/subscribe/result",
  biz_content: "{}",
};

function renderCheckoutPage(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/profile/subscribe/checkout" element={<CheckoutPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CheckoutPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  beforeEach(() => {
    fetchSubscriptionMock.mockReset();
    buildAlipayCheckoutFormMock.mockReset();
    toastMock.mockReset();
  });

  it("renders the order summary from the stored payment order", async () => {
    saveCheckoutOrder(payment);
    fetchSubscriptionMock.mockResolvedValue(subscription);
    renderCheckoutPage("/profile/subscribe/checkout?out_trade_no=order-1");

    expect(screen.getByText("加载订单…")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("标准包")).toBeInTheDocument();
    });
    expect(screen.getByText("¥19.90")).toBeInTheDocument();
    expect(screen.getByText("order-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "去支付宝支付" })).toBeInTheDocument();
  });

  it("shows the fallback product name when the package lookup fails", async () => {
    saveCheckoutOrder(payment);
    fetchSubscriptionMock.mockRejectedValueOnce(new Error("network"));
    renderCheckoutPage("/profile/subscribe/checkout?out_trade_no=order-1");

    await waitFor(() => {
      expect(screen.getByText("AI 对话次数包")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "去支付宝支付" })).toBeInTheDocument();
  });

  it("shows a missing-order hint when the stored order is absent", async () => {
    renderCheckoutPage("/profile/subscribe/checkout?out_trade_no=order-2");

    await waitFor(() => {
      expect(screen.getByText("订单信息缺失或已过期，请重新下单")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "返回订阅页" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "去支付宝支付" })).not.toBeInTheDocument();
  });

  it("shows a missing-order hint when out_trade_no is absent", async () => {
    renderCheckoutPage("/profile/subscribe/checkout");

    await waitFor(() => {
      expect(screen.getByText("订单信息缺失或已过期，请重新下单")).toBeInTheDocument();
    });
  });

  it("submits the alipay checkout form when the pay button is clicked", async () => {
    saveCheckoutOrder(payment);
    fetchSubscriptionMock.mockResolvedValue(subscription);

    const submitSpy = vi.fn();
    const fakeForm = document.createElement("form");
    fakeForm.submit = submitSpy;
    buildAlipayCheckoutFormMock.mockReturnValue(fakeForm);
    const appendSpy = vi.spyOn(document.body, "appendChild");

    renderCheckoutPage("/profile/subscribe/checkout?out_trade_no=order-1");

    const payButton = await screen.findByRole("button", { name: "去支付宝支付" });
    await userEvent.click(payButton);

    expect(buildAlipayCheckoutFormMock).toHaveBeenCalledWith(payment);
    expect(appendSpy).toHaveBeenCalledWith(fakeForm);
    expect(submitSpy).toHaveBeenCalledTimes(1);
    fakeForm.remove();
  });

  it("shows a toast when submitting the alipay form throws", async () => {
    saveCheckoutOrder(payment);
    fetchSubscriptionMock.mockResolvedValue(subscription);
    buildAlipayCheckoutFormMock.mockImplementation(() => {
      throw new Error("form error");
    });

    renderCheckoutPage("/profile/subscribe/checkout?out_trade_no=order-1");

    const payButton = await screen.findByRole("button", { name: "去支付宝支付" });
    await userEvent.click(payButton);

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "支付跳转失败", description: "form error" }),
      );
    });
    await act(async () => {});
    expect(screen.getByRole("button", { name: "去支付宝支付" })).not.toBeDisabled();
  });
});
