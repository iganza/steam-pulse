import type { Metadata } from "next";
import { Suspense } from "react";
import { SearchClient } from "./SearchClient";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ searchParams }: Props): Promise<Metadata> {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q : undefined;
  return {
    title: q ? `Search: ${q}` : "Browse Games",
    description: q
      ? `Steam games matching "${q}" — player sentiment analysis and insights.`
      : "Browse and search 100,000+ Steam games with in-depth review analysis.",
    openGraph: {
      title: q ? `Search: ${q} — SteamPulse` : "Browse Steam Games — SteamPulse",
      description: q
        ? `Steam games matching "${q}" — player sentiment analysis and insights.`
        : "Browse and search 100,000+ Steam games with in-depth review analysis.",
      url: q
        ? `https://steampulse.io/search?q=${encodeURIComponent(q)}`
        : "https://steampulse.io/search",
      images: [{ url: "/og-default.png", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title: q ? `Search: ${q} — SteamPulse` : "Browse Steam Games — SteamPulse",
      description: q
        ? `Steam games matching "${q}" — player sentiment analysis and insights.`
        : "Browse and search 100,000+ Steam games with in-depth review analysis.",
    },
    alternates: {
      canonical: q
        ? `https://steampulse.io/search?q=${encodeURIComponent(q)}`
        : "https://steampulse.io/search",
    },
  };
}

export default async function SearchPage({ searchParams }: Props) {
  const sp = await searchParams;
  const initialParams: Record<string, string> = {};
  for (const [key, val] of Object.entries(sp)) {
    if (typeof val === "string") initialParams[key] = val;
    else if (Array.isArray(val) && val.length > 0) initialParams[key] = val[0];
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center"><p className="text-sm text-muted-foreground font-mono">Loading...</p></div>}>
      <SearchClient initialParams={initialParams} />
    </Suspense>
  );
}
