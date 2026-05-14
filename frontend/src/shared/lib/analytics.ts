/**
 * Amplitude 数据埋点模块
 *
 * 统一封装 Amplitude SDK 的初始化和事件追踪，
 * 业务代码通过 analytics.track() 上报事件，无需直接依赖 Amplitude API。
 */

import * as amplitude from "@amplitude/analytics-browser";

const AMPLITUDE_API_KEY = import.meta.env.VITE_AMPLITUDE_API_KEY ?? "";

let initialized = false;

/**
 * 初始化 Amplitude SDK。应在应用启动时调用一次。
 */
export function initAnalytics(): void {
  if (initialized || !AMPLITUDE_API_KEY) return;

  amplitude.init(AMPLITUDE_API_KEY, {
    autocapture: true,
  });

  initialized = true;
}

/**
 * 设置当前用户身份（登录后调用）。
 */
export function identifyUser(userId: string, properties?: Record<string, unknown>): void {
  if (!initialized) return;
  amplitude.setUserId(userId);
  if (properties) {
    const identifyEvent = new amplitude.Identify();
    for (const [key, value] of Object.entries(properties)) {
      identifyEvent.set(key, value as string);
    }
    amplitude.identify(identifyEvent);
  }
}

/**
 * 清除用户身份（登出时调用）。
 */
export function resetAnalytics(): void {
  if (!initialized) return;
  amplitude.reset();
}

/**
 * 追踪自定义事件。
 */
export function trackEvent(eventName: string, properties?: Record<string, unknown>): void {
  if (!initialized) return;
  amplitude.track(eventName, properties);
}
