import type { Metadata } from "next";
import { Suspense } from "react";
import { NewReleasesClient } from "./NewReleasesClient";

export const metadata: Metadata = {
  title: "New Releases",
  description: "Newly released Steam games and freshly analyzed titles with review intelligence.",
  openGraph: {
    title: "New Steam Releases — SteamPulse",
    description: "Newly released Steam games and freshly analyzed titles with review intelligence.",
    url: "https://steampulse.io/new-releases",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "New Steam Releases — SteamPulse",
    description: "Newly released Steam games and freshly analyzed titles with review intelligence.",
  },
  alternates: { canonical: "https://steampulse.io/new-releases" },
};

export default function NewReleasesPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center"><p className="text-sm text-muted-foreground font-mono">Loading...</p></div>}>
      <NewReleasesClient />
    </Suspense>
  );
}
