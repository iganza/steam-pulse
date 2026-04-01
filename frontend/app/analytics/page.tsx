import type { Metadata } from "next";
import { AnalyticsClient } from "./AnalyticsClient";

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
      <AnalyticsClient />
    </main>
  );
}
