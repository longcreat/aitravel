import { afterEach, describe, expect, it } from "vitest";

import {
  LOCATION_PERMISSION_KEY,
  clearStoredLocationPermission,
  getStoredLocationPermission,
  isLocationPermissionEnabled,
  setStoredLocationPermission,
} from "@/features/location/lib/location-permission";

describe("location-permission", () => {
  afterEach(() => {
    clearStoredLocationPermission();
  });

  it("defaults to disabled", () => {
    expect(getStoredLocationPermission()).toBe("disabled");
    expect(isLocationPermissionEnabled()).toBe(false);
  });

  it("persists the enabled state to localStorage", () => {
    setStoredLocationPermission("enabled");

    expect(window.localStorage.getItem(LOCATION_PERMISSION_KEY)).toBe("enabled");
    expect(getStoredLocationPermission()).toBe("enabled");
    expect(isLocationPermissionEnabled()).toBe(true);
  });
});
