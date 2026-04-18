const defaultBaseUrl = "http://localhost:8000";

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? defaultBaseUrl,
  amapJsKey: import.meta.env.VITE_AMAP_JS_KEY ?? "",
  amapSecurityJsCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE ?? "",
};
