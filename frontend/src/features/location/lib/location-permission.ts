export type LocationPermissionState = "enabled" | "disabled";

export const LOCATION_PERMISSION_KEY = "ai-travel-location-permission";

function normalizeLocationPermission(value: string | null): LocationPermissionState {
  return value === "enabled" ? "enabled" : "disabled";
}

export function getStoredLocationPermission(): LocationPermissionState {
  if (typeof window === "undefined") {
    return "disabled";
  }

  return normalizeLocationPermission(window.localStorage.getItem(LOCATION_PERMISSION_KEY));
}

export function setStoredLocationPermission(permission: LocationPermissionState): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(LOCATION_PERMISSION_KEY, permission);
}

export function clearStoredLocationPermission(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(LOCATION_PERMISSION_KEY);
}

export function isLocationPermissionEnabled(): boolean {
  return getStoredLocationPermission() === "enabled";
}

export function getLocationPermissionSummary(permission = getStoredLocationPermission()): string {
  return permission === "enabled" ? "已开启" : "未开启";
}
