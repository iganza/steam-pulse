import type { Metadata } from "next";
import { Suspense } from "react";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Compare Games — SteamPulse",
  description:
    "Side-by-side comparison of Steam games across sentiment, hidden gem score, promise gap, and audience fit.",
};

export default function ComparePage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="font-serif text-2xl font-bold mb-1">Compare Games</h1>
        <p className="text-muted-foreground text-sm mb-6">
          Pick up to 4 games and line them up across every metric SteamPulse computes.
        </p>
        <Suspense
          fallback={
            <p className="text-sm text-muted-foreground font-mono py-8">
              Loading compare...
            </p>
          }
        >
          <ToolkitShell
            defaultLens="compare"
            visibleLenses={["compare"]}
          />
        </Suspense>
      </div>
    </main>
  );
}
