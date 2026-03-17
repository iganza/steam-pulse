import type { Metadata } from "next";
import { Suspense } from "react";
import { getGames, getGenres } from "@/lib/api";
import { GameCard } from "@/components/game/GameCard";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { SearchClient } from "@/app/search/SearchClient";
import type { Game, Genre } from "@/lib/types";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} Games`,
    description: `Browse ${name} games on Steam with AI-analyzed player sentiment, hidden gems, and review intelligence.`,
  };
}

export default async function GenrePage({ params }: Props) {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  // Fetch genre info and top picks in parallel
  const [genresResult, topPicksResult] = await Promise.allSettled([
    getGenres(),
    getGames({ genre: slug, sort: "sentiment_score", min_reviews: 200, limit: 3 }),
  ]);

  const genres = genresResult.status === "fulfilled" ? genresResult.value : [];
  const genreInfo = genres.find((g: Genre) => g.slug === slug);
  const topPicks: Game[] =
    topPicksResult.status === "fulfilled" ? topPicksResult.value.games ?? [] : [];

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
          <p className="text-sm text-muted-foreground font-mono">
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

        {/* Full catalog with filters */}
        <Suspense fallback={<p className="text-sm text-muted-foreground font-mono py-8">Loading...</p>}>
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
