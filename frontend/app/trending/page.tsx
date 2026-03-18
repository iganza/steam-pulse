import type { Metadata } from "next";
import Link from "next/link";
import { TrendingUp, Star, Gem, ChevronRight } from "lucide-react";
import { getGames } from "@/lib/api";
import { GameCard } from "@/components/game/GameCard";
import type { Game } from "@/lib/types";

export const metadata: Metadata = {
  title: "Trending",
  description: "Trending Steam games \u2014 most reviewed, top rated, and hidden gems with in-depth analysis.",
  openGraph: {
    title: "Trending Steam Games — SteamPulse",
    description: "Most reviewed, top rated, and hidden gems with in-depth analysis.",
    url: "https://steampulse.io/trending",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Trending Steam Games — SteamPulse",
    description: "Most reviewed, top rated, and hidden gems with in-depth analysis.",
  },
  alternates: { canonical: "https://steampulse.io/trending" },
};

export default async function TrendingPage() {
  const [risingResult, topRatedResult, gemsResult] = await Promise.allSettled([
    getGames({ sort: "review_count", limit: 12 }),
    getGames({ sort: "sentiment_score", min_reviews: 200, limit: 12 }),
    getGames({ sort: "hidden_gem_score", limit: 12 }),
  ]);

  const rising: Game[] = risingResult.status === "fulfilled" ? risingResult.value.games ?? [] : [];
  const topRated: Game[] = topRatedResult.status === "fulfilled" ? topRatedResult.value.games ?? [] : [];
  const gems: Game[] = gemsResult.status === "fulfilled" ? gemsResult.value.games ?? [] : [];

  const sections = [
    {
      label: "Rising",
      icon: <TrendingUp className="w-4 h-4" style={{ color: "var(--teal)" }} />,
      games: rising,
      seeAll: "/search?sort=review_count",
    },
    {
      label: "Top Rated",
      icon: <Star className="w-4 h-4" style={{ color: "var(--positive)" }} />,
      games: topRated,
      seeAll: "/search?sort=sentiment_score&min_reviews=200",
    },
    {
      label: "Hidden Gems",
      icon: <Gem className="w-4 h-4" style={{ color: "var(--gem)" }} />,
      games: gems,
      seeAll: "/search?sort=hidden_gem_score",
    },
  ];

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-16">
        <h1 className="font-serif text-4xl font-bold" style={{ letterSpacing: "-0.03em" }}>
          Trending
        </h1>

        {sections.map(
          (section) =>
            section.games.length > 0 && (
              <section key={section.label}>
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    {section.icon}
                    <h2 className="font-serif text-xl font-semibold">{section.label}</h2>
                  </div>
                  <Link
                    href={section.seeAll}
                    className="flex items-center gap-1 text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
                  >
                    See all <ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {section.games.map((game) => (
                    <GameCard key={game.appid} game={game} />
                  ))}
                </div>
              </section>
            ),
        )}

        {rising.length === 0 && topRated.length === 0 && gems.length === 0 && (
          <div className="text-center py-20">
            <p className="text-base text-muted-foreground">No trending data available yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export const revalidate = 3600;
