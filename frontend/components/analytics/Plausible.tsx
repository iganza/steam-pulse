"use client";

import { useEffect } from "react";

// Module-scoped guard: tracker package throws if init() runs twice, and React
// Strict Mode in dev invokes effects twice on mount.
let initialized = false;

export function Plausible() {
  useEffect(() => {
    if (initialized) return;
    if (process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED !== "true") return;
    initialized = true;
    void import("@plausible-analytics/tracker").then(({ init }) => {
      init({ domain: "steampulse.io", endpoint: "/stats/api/event" });
    });
  }, []);
  return null;
}
