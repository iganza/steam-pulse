import type { Metadata } from "next";
import Link from "next/link";
import { Gem, TrendingUp, ChevronRight, Star, Sparkles, Clock } from "lucide-react";
import { HeroSearch } from "@/components/layout/HeroSearch";
import { getGames, getGenres, getTopTags } from "@/lib/api";
import { GameCard } from "@/components/game/GameCard";
import type { Game } from "@/lib/types";

export const metadata: Metadata = {
  title: "SteamPulse: Steam Game Intelligence",
  description:
    "Deep review intelligence for 6,000+ Steam games. Discover what players love, hate, and want next.",
  openGraph: {
    title: "SteamPulse: Steam Game Intelligence",
    description: "Deep review intelligence for 6,000+ Steam games.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse: Steam Game Intelligence",
    description: "Deep review intelligence for 6,000+ Steam games.",
    images: ["/og-default.png"],
  },
  alternates: {
    canonical: "https://steampulse.io",
  },
};

export default async function HomePage() {
  const [popular, topRated, hiddenGems, newReleases, justAnalyzed, genres, tags] =
    await Promise.allSettled([
      getGames({ sort: "review_count", limit: 8 }),
      getGames({ sort: "sentiment_score", min_reviews: 200, limit: 8 }),
      getGames({ sort: "hidden_gem_score", limit: 8 }),
      getGames({ sort: "release_date", limit: 8 }),
      getGames({ sort: "last_analyzed", limit: 6 }),
      getGenres(),
      getTopTags(50),
    ]);

  const popularGames: Game[] =
    popular.status === "fulfilled" ? popular.value.games ?? [] : [];
  const topRatedGames: Game[] =
    topRated.status === "fulfilled" ? topRated.value.games ?? [] : [];
  const gemGames: Game[] =
    hiddenGems.status === "fulfilled" ? hiddenGems.value.games ?? [] : [];
  const newGames: Game[] =
    newReleases.status === "fulfilled" ? newReleases.value.games ?? [] : [];
  const analyzedGames: Game[] =
    justAnalyzed.status === "fulfilled" ? justAnalyzed.value.games ?? [] : [];
  const genreList = genres.status === "fulfilled" ? genres.value : [];
  const tagList = tags.status === "fulfilled" ? tags.value : [];

  const rows: {
    label: string;
    icon: React.ReactNode;
    games: Game[];
    seeAll: string;
  }[] = [
    {
      label: "Most Popular",
      icon: <TrendingUp className="w-4 h-4" style={{ color: "var(--teal)" }} />,
      games: popularGames,
      seeAll: "/search?sort=review_count",
    },
    {
      label: "Top Rated",
      icon: <Star className="w-4 h-4" style={{ color: "var(--positive)" }} />,
      games: topRatedGames,
      seeAll: "/search?sort=sentiment_score",
    },
    {
      label: "Hidden Gems",
      icon: <Gem className="w-4 h-4" style={{ color: "var(--gem)" }} />,
      games: gemGames,
      seeAll: "/search?sort=hidden_gem_score",
    },
    {
      label: "New on Steam",
      icon: <Sparkles className="w-4 h-4" style={{ color: "var(--teal)" }} />,
      games: newGames,
      seeAll: "/new-releases",
    },
  ];

  const hasAnyGames = rows.some((r) => r.games.length > 0);

  return (
    <div className="min-h-screen bg-background">
      {/* Search Hero */}
      <header className="relative">
        <div
          className="absolute inset-0 opacity-30 pointer-events-none overflow-hidden"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(45,185,212,0.15), transparent)",
          }}
        />
        <div className="relative max-w-3xl mx-auto px-6 pt-20 pb-16 text-center">
          <h1
            className="font-serif text-4xl md:text-5xl font-bold text-foreground mb-6 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            Discover Steam Games
          </h1>
          <HeroSearch />
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 pb-24 space-y-16">
        {/* Discovery Rows */}
        {rows.map(
          (row) =>
            row.games.length > 0 && (
              <section key={row.label}>
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    {row.icon}
                    <h2 className="font-serif text-xl font-semibold">{row.label}</h2>
                  </div>
                  <Link
                    href={row.seeAll}
                    className="flex items-center gap-1 text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
                  >
                    See all <ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {row.games.map((game) => (
                    <GameCard key={game.appid} game={game} />
                  ))}
                </div>
              </section>
            ),
        )}

        {/* Just Analyzed */}
        {analyzedGames.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4" style={{ color: "var(--teal)" }} />
                <h2 className="font-serif text-xl font-semibold">Just Analyzed</h2>
              </div>
              <Link
                href="/search?sort=last_analyzed"
                className="flex items-center gap-1 text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
              >
                See all <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {analyzedGames.map((game) => (
                <GameCard key={game.appid} game={game} />
              ))}
            </div>
          </section>
        )}

        {/* Browse by Genre */}
        {genreList.length > 0 && (
          <section>
            <h2 className="font-serif text-xl font-semibold mb-6">Browse by Genre</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {genreList.slice(0, 16).map((genre) => (
                <Link
                  key={genre.id}
                  href={`/genre/${genre.slug}`}
                  className="group px-4 py-3 rounded-xl text-base font-mono transition-all duration-200 hover:scale-[1.02]"
                  style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                >
                  <span className="text-foreground/80 group-hover:text-foreground transition-colors">
                    {genre.name}
                  </span>
                  {genre.game_count != null && (
                    <span className="block text-xs text-muted-foreground mt-0.5">
                      {genre.game_count.toLocaleString()} games
                    </span>
                  )}
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Browse by Tag */}
        {tagList.length > 0 && (
          <section>
            <h2 className="font-serif text-xl font-semibold mb-6">Browse by Tag</h2>
            <div className="flex flex-wrap gap-2">
              {tagList.map((tag) => (
                <Link
                  key={tag.id}
                  href={`/tag/${tag.slug}`}
                  className="text-sm px-3 py-1.5 rounded-full font-mono transition-colors hover:text-foreground"
                  style={{
                    background: "rgba(45,185,212,0.06)",
                    border: "1px solid rgba(45,185,212,0.15)",
                    color: "var(--teal)",
                  }}
                >
                  {tag.name}
                  {tag.game_count != null && (
                    <span className="text-muted-foreground ml-1">
                      {tag.game_count.toLocaleString()}
                    </span>
                  )}
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Empty state */}
        {!hasAnyGames && (
          <div className="text-center py-20">
            <p className="font-mono text-base text-muted-foreground mb-2">
              No games in the database yet.
            </p>
            <p className="text-sm text-muted-foreground">
              Run{" "}
              <code className="px-1.5 py-0.5 rounded bg-secondary font-mono text-[11px]">
                poetry run python scripts/seed.py --limit 500
              </code>{" "}
              to seed the catalog.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

export const dynamic = "force-dynamic";
