import AMapLoader from "@amap/amap-jsapi-loader";

import { env } from "@/shared/config/env";

type LocationErrorCode =
  | "key-missing"
  | "sdk-load-failed"
  | "permission-denied"
  | "timeout"
  | "position-unavailable";

interface AMapAddressComponent {
  province?: string | string[];
  city?: string | string[];
  district?: string;
}

interface AMapLocationResult {
  info?: string;
  message?: string;
  addressComponent?: AMapAddressComponent;
  formattedAddress?: string;
}

interface AMapGeolocation {
  getCurrentPosition: (callback: (status: string, result: AMapLocationResult) => void) => void;
}

interface AMapNamespace {
  Geolocation: new (options: Record<string, unknown>) => AMapGeolocation;
}

export class AMapLocationError extends Error {
  code: LocationErrorCode;

  constructor(code: LocationErrorCode, message: string) {
    super(message);
    this.name = "AMapLocationError";
    this.code = code;
  }
}

let amapPromise: Promise<AMapNamespace> | null = null;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, errorFactory: () => Error): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(errorFactory()), timeoutMs);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  return normalized || null;
}

function normalizeAreaName(value: unknown): string | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const normalized = normalizeText(item);
      if (normalized) {
        return normalized;
      }
    }
    return null;
  }

  return normalizeText(value);
}

function buildDisplayName(result: AMapLocationResult): string | null {
  const addressComponent = result.addressComponent ?? {};
  const province = normalizeAreaName(addressComponent.province);
  const city = normalizeAreaName(addressComponent.city);
  const district = normalizeText(addressComponent.district);
  const formattedAddress = normalizeText(result.formattedAddress);

  const parts: string[] = [];
  if (city) {
    parts.push(city);
  } else if (province) {
    parts.push(province);
  }

  if (district && district !== parts[parts.length - 1]) {
    parts.push(district);
  }

  const displayName = parts.join("");
  if (displayName) {
    return displayName;
  }

  return formattedAddress;
}

function getSecurityConfig() {
  const securityJsCode = env.amapSecurityJsCode.trim();
  if (!securityJsCode) {
    return null;
  }

  return { securityJsCode };
}

async function loadAMap(): Promise<AMapNamespace> {
  const key = env.amapJsKey.trim();
  if (!key) {
    throw new AMapLocationError("key-missing", "高德 JS API Key 未配置");
  }

  if (!amapPromise) {
    const securityConfig = getSecurityConfig();
    if (securityConfig) {
      (window as Window & { _AMapSecurityConfig?: { securityJsCode: string } })._AMapSecurityConfig = securityConfig;
    }

    amapPromise = AMapLoader.load({
      key,
      version: "2.0",
      plugins: ["AMap.Geolocation"],
    }) as Promise<AMapNamespace>;
  }

  try {
    return await withTimeout(amapPromise, 10000, () => new AMapLocationError("sdk-load-failed", "高德定位服务加载超时"));
  } catch (_error) {
    amapPromise = null;
    throw new AMapLocationError("sdk-load-failed", "高德定位服务加载失败");
  }
}

function toLocationError(result: AMapLocationResult | null | undefined): AMapLocationError {
  const rawInfo = `${result?.info ?? ""} ${result?.message ?? ""}`.toLowerCase();

  if (rawInfo.includes("permission") || rawInfo.includes("denied") || rawInfo.includes("notgranted")) {
    return new AMapLocationError("permission-denied", "未获取到定位权限");
  }

  if (rawInfo.includes("timeout")) {
    return new AMapLocationError("timeout", "定位请求超时");
  }

  return new AMapLocationError("position-unavailable", "暂时无法识别当前位置");
}

export function getLocationFallbackMessage(error: unknown): string {
  if (error instanceof AMapLocationError) {
    switch (error.code) {
      case "key-missing":
      case "sdk-load-failed":
      case "position-unavailable":
        return "暂时无法识别当前位置，已先按当前位置为你发起请求。";
      case "permission-denied":
        return "未拿到定位权限，已先按当前位置为你发起请求。";
      case "timeout":
        return "定位请求超时，已先按当前位置为你发起请求。";
      default:
        return "未拿到当前位置，已先按当前位置为你发起请求。";
    }
  }

  return "未拿到当前位置，已先按当前位置为你发起请求。";
}

export async function getCurrentLocationName(): Promise<string | null> {
  const AMap = await loadAMap();

  return withTimeout(
    new Promise<string | null>((resolve, reject) => {
      const geolocation = new AMap.Geolocation({
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 5 * 60 * 1000,
        convert: true,
        needAddress: true,
        showButton: false,
        extensions: "base",
      });

      geolocation.getCurrentPosition((status, result) => {
        if (status !== "complete") {
          reject(toLocationError(result));
          return;
        }

        resolve(buildDisplayName(result));
      });
    }),
    12000,
    () => new AMapLocationError("timeout", "定位请求超时"),
  );
}
