import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/features/auth/model/auth.context";
import { RequireAuthRoute } from "@/features/auth/ui/require-auth-route";
import {
  clearStoredAccessToken,
  clearStoredAuthUser,
  setStoredAccessToken,
  setStoredAuthUser,
} from "@/features/auth/model/auth.storage";
import {
  LOCATION_PERMISSION_KEY,
  clearStoredLocationPermission,
} from "@/features/location/lib/location-permission";
import { LocationPermissionPage } from "@/features/profile/ui/location-permission-page";
import { ProfilePage } from "@/features/profile/ui/profile-page";
import { ProfilePermissionsPage } from "@/features/profile/ui/profile-permissions-page";
import { TabLayout } from "@/shared/layouts/tab-layout";

function renderProfileFlow(initialPath = "/profile") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<TabLayout />}>
            <Route path="chat" element={<div>chat-page</div>} />
            <Route element={<RequireAuthRoute />}>
              <Route path="profile" element={<ProfilePage />} />
              <Route path="profile/permissions" element={<ProfilePermissionsPage />} />
              <Route path="profile/permissions/location" element={<LocationPermissionPage />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Profile permissions flow", () => {
  afterEach(() => {
    cleanup();
    clearStoredAccessToken();
    clearStoredAuthUser();
    clearStoredLocationPermission();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("opens the permissions flow and persists updates through the profile settings flow", async () => {
    setStoredAccessToken("token-profile-permissions");
    setStoredAuthUser({
      id: "user-profile",
      email: "profile@example.com",
      nickname: "profile",
      created_at: "2026-04-08T00:00:00Z",
      updated_at: "2026-04-08T00:00:00Z",
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/auth/me") && method === "GET") {
        return {
          ok: true,
          status: 200,
          json: async (): Promise<unknown> => ({
            id: "user-profile",
            email: "profile@example.com",
            nickname: "profile",
            created_at: "2026-04-08T00:00:00Z",
            updated_at: "2026-04-08T00:00:00Z",
          }),
          text: async (): Promise<string> => "",
        };
      }

      return {
        ok: false,
        status: 404,
        text: async (): Promise<string> => "not found",
      };
    });

    vi.stubGlobal("fetch", fetchMock);
    renderProfileFlow();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "open-permissions" })).toBeInTheDocument();
    });
    expect(screen.queryByText("定位 未开启")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "open-permissions" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "open-location-permission" })).toBeInTheDocument();
    });
    expect(screen.queryByText("权限管理")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "你可以自行决定是否允许应用在需要时读取位置信息。位置信息只会在本设备内使用，不会默认共享。",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("未开启")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "open-location-permission" }));

    const switchButton = await screen.findByRole("switch", { name: "toggle-location-permission" });
    expect(screen.queryByText("开启后，应用可以在需要时尝试读取你的位置，用于本地推荐和上下文。真正的系统授权仍由浏览器或系统控制。")).not.toBeInTheDocument();
    expect(switchButton).toHaveAttribute("aria-checked", "false");

    await userEvent.click(switchButton);

    expect(switchButton).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem(LOCATION_PERMISSION_KEY)).toBe("enabled");

    await userEvent.click(screen.getByRole("button", { name: "back-location-permission" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "open-location-permission" })).toBeInTheDocument();
    });
    expect(screen.getByText("已开启")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "back-profile-permissions" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "open-permissions" })).toBeInTheDocument();
    });
    expect(screen.queryByText("定位 已开启")).not.toBeInTheDocument();
  });
});
