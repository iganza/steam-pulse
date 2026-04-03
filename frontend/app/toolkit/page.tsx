import type { Metadata } from "next";
import { Suspense } from "react";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

export const metadata: Metadata = {
  title: "Toolkit — SteamPulse",
  description:
    "Explore Steam game intelligence with filters, comparisons, and market analysis.",
};

export default function ToolkitPage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="font-serif text-2xl font-bold mb-1">Toolkit</h1>
        <p className="text-muted-foreground text-sm mb-6">
          Add filters to explore the Steam catalog. Switch lenses to see
          different perspectives.
        </p>
        <Suspense fallback={<p className="text-sm text-muted-foreground font-mono py-8">Loading toolkit...</p>}>
          <ToolkitShell />
        </Suspense>
      </div>
    </main>
  );
}
