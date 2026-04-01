import type { Metadata } from "next";
import { Suspense } from "react";
import { getGames, getGenres, getPricePositioning, getReleaseTiming, getPlatformGaps } from "@/lib/api";
import { GameCard } from "@/components/game/GameCard";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { SearchClient } from "@/app/search/SearchClient";
import { PricePositioning } from "@/components/analytics/PricePositioning";
import { ReleaseTiming } from "@/components/analytics/ReleaseTiming";
import { PlatformGaps } from "@/components/analytics/PlatformGaps";
import type { Game, Genre } from "@/lib/types";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} Games`,
    description: `Browse ${name} games on Steam with player sentiment analysis, hidden gems, and review intelligence.`,
    openGraph: {
      title: `${name} Games on Steam — SteamPulse`,
      description: `Browse ${name} games with player sentiment analysis, hidden gems, and review intelligence.`,
      url: `https://steampulse.io/genre/${slug}`,
      images: [{ url: "/og-default.png", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${name} Games on Steam — SteamPulse`,
      description: `Browse ${name} games with player sentiment analysis, hidden gems, and review intelligence.`,
    },
    alternates: { canonical: `https://steampulse.io/genre/${slug}` },
  };
}

export default async function GenrePage({ params }: Props) {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  // Fetch genre info, top picks, and market analytics in parallel
  const [genresResult, topPicksResult, pricingResult, timingResult, platformsResult] = await Promise.allSettled([
    getGenres(),
    getGames({ genre: slug, sort: "sentiment_score", min_reviews: 200, limit: 3 }),
    getPricePositioning(slug),
    getReleaseTiming(slug),
    getPlatformGaps(slug),
  ]);

  const genres = genresResult.status === "fulfilled" ? genresResult.value : [];
  const genreInfo = genres.find((g: Genre) => g.slug === slug);
  const topPicks: Game[] =
    topPicksResult.status === "fulfilled" ? topPicksResult.value.games ?? [] : [];
  const pricing = pricingResult.status === "fulfilled" ? pricingResult.value : null;
  const timing = timingResult.status === "fulfilled" ? timingResult.value : null;
  const platforms = platformsResult.status === "fulfilled" ? platformsResult.value : null;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Browse", href: "/search" },
            { label: name },
          ]}
        />

        <div className="mt-6 mb-10">
          <h1
            className="font-serif text-4xl font-bold mb-2"
            style={{ letterSpacing: "-0.03em" }}
          >
            {name}
          </h1>
          <p className="text-base text-muted-foreground font-mono">
            {genreInfo?.game_count?.toLocaleString() ?? "?"} games
            {genreInfo?.analyzed_count != null && ` \u00b7 ${genreInfo.analyzed_count.toLocaleString()} analyzed`}
          </p>
        </div>

        {/* Top Picks */}
        {topPicks.length > 0 && (
          <section className="mb-12">
            <h2 className="font-serif text-lg font-semibold mb-4">Top Picks</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {topPicks.map((game) => (
                <GameCard key={game.appid} game={game} />
              ))}
            </div>
          </section>
        )}

        {/* Market Intelligence */}
        {(pricing || timing || platforms) && (
          <section className="mb-12 space-y-6">
            <h2 className="font-serif text-lg font-semibold">Market Intelligence</h2>
            {pricing && <PricePositioning data={pricing} />}
            {timing && <ReleaseTiming data={timing} />}
            {platforms && <PlatformGaps data={platforms} />}
          </section>
        )}

        {/* Full catalog with filters */}
        <Suspense fallback={<p className="text-base text-muted-foreground font-mono py-8">Loading...</p>}>
          <SearchClient
            initialParams={{}}
            initialFilters={{ genre: slug }}
            hideGenreFilter
          />
        </Suspense>
      </div>
    </div>
  );
}

export const revalidate = 3600;
