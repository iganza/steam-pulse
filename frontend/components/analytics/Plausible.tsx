"use client";

import { useEffect } from "react";

export function Plausible() {
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_PLAUSIBLE_ENABLED !== "true") return;
    void import("@plausible-analytics/tracker").then(({ init }) => {
      init({ domain: "steampulse.io", endpoint: "/stats/api/event" });
    });
  }, []);
  return null;
}
