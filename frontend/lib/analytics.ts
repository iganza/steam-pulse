import type { PlausibleEventOptions } from "@plausible-analytics/tracker";

const enabled = process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED === "true";

declare global {
  interface Window {
    plausible?: (name: string, options?: PlausibleEventOptions) => void;
  }
}

export function trackEvent(name: string, options?: PlausibleEventOptions) {
  if (!enabled) return;
  if (typeof window === "undefined") return;
  window.plausible?.(name, options);
}
