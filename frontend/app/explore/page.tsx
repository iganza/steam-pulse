import type { Metadata } from "next";
import { Suspense } from "react";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Explore — SteamPulse",
  description:
    "Explore catalog-wide Steam trends: release volume, sentiment, genre shifts, pricing, platform support, and more.",
};

export default function ExplorePage() {
  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">Explore</h1>
      <p className="text-muted-foreground text-sm mb-6">
        Catalog-wide trends across the Steam ecosystem. Add filters above to scope.
      </p>
      <Suspense fallback={<p className="text-base text-muted-foreground font-mono py-8">Loading...</p>}>
        <ToolkitShell
          defaultLens="trends"
          visibleLenses={["trends", "builder"]}
        />
      </Suspense>
    </main>
  );
}
