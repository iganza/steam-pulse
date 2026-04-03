import type { Metadata } from "next";
import { Suspense } from "react";
import { AnalyticsClient } from "./AnalyticsClient";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Steam Analytics — SteamPulse",
  description:
    "Explore catalog-wide Steam trends: release volume, sentiment, genre shifts, pricing, platform support, and more.",
};

export default function AnalyticsPage() {
  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">Analytics</h1>
      <p className="text-muted-foreground text-sm mb-6">
        Catalog-wide trends across the Steam ecosystem.
      </p>
      <Suspense fallback={<p className="text-base text-muted-foreground font-mono py-8">Loading...</p>}>
        <ToolkitShell
          defaultLens="trends"
          visibleLenses={["trends", "market-map", "explorer"]}
          lensContent={{
            trends: <AnalyticsClient />,
          }}
        />
      </Suspense>
    </main>
  );
}
