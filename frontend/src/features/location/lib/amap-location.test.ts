import { afterEach, describe, expect, it, vi } from "vitest";

import { getCurrentLocationName } from "@/features/location/lib/amap-location";
import {
  clearStoredLocationPermission,
  setStoredLocationPermission,
} from "@/features/location/lib/location-permission";

const { loadMock } = vi.hoisted(() => ({
  loadMock: vi.fn(),
}));

vi.mock("@amap/amap-jsapi-loader", () => ({
  default: {
    load: loadMock,
  },
}));

describe("amap-location", () => {
  afterEach(() => {
    clearStoredLocationPermission();
    loadMock.mockReset();
  });

  it("short-circuits before loading AMap when location permission is disabled", async () => {
    const result = await getCurrentLocationName();

    expect(result).toBeNull();
    expect(loadMock).not.toHaveBeenCalled();
  });

  it("tries to load AMap when location permission is enabled", async () => {
    setStoredLocationPermission("enabled");
    loadMock.mockRejectedValueOnce(new Error("sdk load failed"));

    await expect(getCurrentLocationName()).rejects.toThrow("高德定位服务加载失败");
    expect(loadMock).toHaveBeenCalledTimes(1);
  });
});
