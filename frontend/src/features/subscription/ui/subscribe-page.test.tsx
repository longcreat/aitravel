import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PaymentOrderResponse,
  SubscriptionStatus,
} from "@/features/subscription/model/subscription.types";
import { SubscribePage } from "@/features/subscription/ui/subscribe-page";

const { fetchSubscriptionMock, createPaymentOrderMock, buildAlipayCheckoutFormMock, toastMock, navigateMock } =
  vi.hoisted(() => ({
    fetchSubscriptionMock: vi.fn(),
    createPaymentOrderMock: vi.fn(),
    buildAlipayCheckoutFormMock: vi.fn(),
    toastMock: vi.fn(),
    navigateMock: vi.fn(),
  }));

vi.mock("@/features/subscription/api/subscription.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/subscription/api/subscription.api")>();
  return {
    ...actual,
    fetchSubscription: fetchSubscriptionMock,
    createPaymentOrder: createPaymentOrderMock,
    buildAlipayCheckoutForm: buildAlipayCheckoutFormMock,
  };
});

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/shared/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/shared/ui")>();
  return {
    ...actual,
    useToast: () => ({ toast: toastMock }),
  };
});

const threePackages: SubscriptionStatus = {
  daily_free_limit: 10,
  free_used: 3,
  remain_count: 150,
  packages: [
    { id: "trial", name: "体验包", price: "9.90", quota: 50 },
    { id: "standard", name: "标准包", price: "19.90", quota: 150 },
    { id: "unlimited", name: "畅玩包", price: "39.90", quota: 500 },
  ],
};

function renderSubscribePage() {
  return render(
    <MemoryRouter>
      <SubscribePage />
    </MemoryRouter>,
  );
}

describe("SubscribePage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    fetchSubscriptionMock.mockReset();
    createPaymentOrderMock.mockReset();
    buildAlipayCheckoutFormMock.mockReset();
    toastMock.mockReset();
    navigateMock.mockReset();
    sessionStorage.clear();
  });

  it("renders all three packages with names and prices", async () => {
    fetchSubscriptionMock.mockResolvedValue(threePackages);
    renderSubscribePage();

    await waitFor(() => {
      expect(screen.getByText("体验包")).toBeInTheDocument();
      expect(screen.getByText("标准包")).toBeInTheDocument();
      expect(screen.getByText("畅玩包")).toBeInTheDocument();
    });
    expect(screen.getByText("¥9.90")).toBeInTheDocument();
    expect(screen.getByText("¥19.90")).toBeInTheDocument();
    expect(screen.getByText("¥39.90")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "立即购买" })).toHaveLength(3);
  });

  it("shows the total remaining quota combining free and purchased counts", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      daily_free_limit: 10,
      free_used: 2,
      remain_count: 150,
      packages: threePackages.packages,
    });
    renderSubscribePage();

    const totalSpan = await screen.findByText("158");
    const statusLine = totalSpan.closest("p");
    expect(statusLine).toHaveTextContent(/剩余可用 158 次/);
    expect(statusLine).toHaveTextContent(/今日免费 8 次 \/ 已购 150 次/);
  });

  it("creates the payment order and navigates to the checkout page on buy", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      daily_free_limit: 10,
      free_used: 0,
      remain_count: 0,
      packages: [threePackages.packages[1]],
    });
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
    createPaymentOrderMock.mockResolvedValue(payment);

    renderSubscribePage();

    const buyButton = await screen.findByRole("button", { name: "立即购买" });
    await userEvent.click(buyButton);

    await waitFor(() => {
      expect(createPaymentOrderMock).toHaveBeenCalledWith("standard");
    });
    expect(buildAlipayCheckoutFormMock).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith("/profile/subscribe/checkout?out_trade_no=order-1");
    const stored = sessionStorage.getItem("wander:checkout-order:order-1");
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored as string)).toMatchObject({ out_trade_no: "order-1", total_amount: "19.90" });
  });

  it("shows an error card and refetches on retry", async () => {
    fetchSubscriptionMock.mockRejectedValueOnce(new Error("network"));
    fetchSubscriptionMock.mockResolvedValueOnce(threePackages);
    renderSubscribePage();

    await waitFor(() => {
      expect(screen.getByText("订阅状态加载失败，请稍后重试")).toBeInTheDocument();
    });
    expect(screen.queryByText("体验包")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(screen.getByText("体验包")).toBeInTheDocument();
    });
    expect(fetchSubscriptionMock).toHaveBeenCalledTimes(2);
  });

  it("shows a spinner while the subscription status is loading", async () => {
    let resolveFetch!: (value: SubscriptionStatus) => void;
    fetchSubscriptionMock.mockReturnValueOnce(
      new Promise<SubscriptionStatus>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    renderSubscribePage();

    expect(screen.getByText("读取订阅状态…")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "立即购买" })).not.toBeInTheDocument();

    await act(async () => {
      resolveFetch(threePackages);
    });

    await waitFor(() => {
      expect(screen.getByText("体验包")).toBeInTheDocument();
    });
  });

  it("shows a toast when creating the payment order fails", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      daily_free_limit: 10,
      free_used: 0,
      remain_count: 0,
      packages: [threePackages.packages[1]],
    });
    createPaymentOrderMock.mockRejectedValueOnce(new Error("HTTP 500"));
    renderSubscribePage();

    const buyButton = await screen.findByRole("button", { name: "立即购买" });
    await userEvent.click(buyButton);

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "下单失败", description: "HTTP 500" }),
      );
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "立即购买" })).not.toBeDisabled();
    });
  });
});
