import type { Metadata } from "next";
import { Suspense } from "react";
import { ReportsClient } from "./ReportsClient";

export const metadata: Metadata = {
  title: "Reports — SteamPulse",
  description: "Browse in-depth review analysis reports for Steam games. See what's been analyzed and request reports for games you care about.",
  openGraph: {
    title: "Reports — SteamPulse",
    description: "Browse in-depth review analysis reports for Steam games. See what's been analyzed and request reports for games you care about.",
    url: "https://steampulse.io/reports",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Reports — SteamPulse",
    description: "Browse in-depth review analysis reports for Steam games.",
  },
  alternates: { canonical: "https://steampulse.io/reports" },
};

export default function ReportsPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center"><p className="text-sm text-muted-foreground font-mono">Loading...</p></div>}>
      <ReportsClient />
    </Suspense>
  );
}
