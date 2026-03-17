import type { Metadata } from "next";
import { Suspense } from "react";
import { NewReleasesClient } from "./NewReleasesClient";

export const metadata: Metadata = {
  title: "New Releases",
  description: "Newly released Steam games and freshly analyzed titles with AI-powered review intelligence.",
};

export default function NewReleasesPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center"><p className="text-sm text-muted-foreground font-mono">Loading...</p></div>}>
      <NewReleasesClient />
    </Suspense>
  );
}
