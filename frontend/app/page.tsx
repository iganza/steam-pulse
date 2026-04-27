import type { Metadata } from "next";
import Link from "next/link";
import { Gem, TrendingUp, ChevronRight, Star, Sparkles, Clock } from "lucide-react";
import { HeroSearch } from "@/components/layout/HeroSearch";
import {
  getDiscoveryFeed,
  getCatalogStats,
  getGenres,
  getTagsGrouped,
  getGameBasics,
  getGenreInsights,
  getHomeIntelSnapshot,
} from "@/lib/api";
import type { GameBasicsEntry } from "@/lib/api";
import { TagBrowser } from "@/components/home/TagBrowser";
import { ProofBar } from "@/components/home/ProofBar";
import { FeaturedReport } from "@/components/home/FeaturedReport";
import { IntelligenceCards } from "@/components/home/IntelligenceCards";
import { MarketTrendsPreview } from "@/components/home/MarketTrendsPreview";
import { ForDevelopers } from "@/components/home/ForDevelopers";
import { FooterCTA } from "@/components/home/FooterCTA";
import { GameCard } from "@/components/game/GameCard";
import type { Game, TagGroup } from "@/lib/types";

const FEATURED_REPORT_SLUG = "roguelike-deckbuilder";

const SHOWCASE_GAMES = [
  { appid: 1086940, slug: "baldurs-gate-3-1086940" },   // RPG / fantasy
  { appid: 413150, slug: "stardew-valley-413150" },     // indie / simulation
  { appid: 1091500, slug: "cyberpunk-2077-1091500" },   // AAA / open-world
] as const;

export const metadata: Metadata = {
  title: "SteamPulse — Steam Game Intelligence",
  description:
    "Player intelligence across 100,000+ Steam games. Sentiment analysis, competitive insights, market trends, and deep review reports — for gamers and game makers.",
  openGraph: {
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "What players really think about every Steam game. Sentiment, trends, and competitive intelligence.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "What players really think about every Steam game. Sentiment, trends, and competitive intelligence.",
    images: ["/og-default.png"],
  },
  alternates: {
    canonical: "https://steampulse.io",
  },
};

export default async function HomePage() {
  const [
    popular,
    topRated,
    hiddenGems,
    newReleases,
    justAnalyzed,
    genres,
    tags,
    catalogStats,
    featuredReport,
    showcaseBasics,
    homeIntel,
  ] = await Promise.allSettled([
    // Discovery rows served from mv_discovery_feeds (pre-computed top-N per kind).
    getDiscoveryFeed("popular", 8),
    getDiscoveryFeed("top_rated", 8),
    getDiscoveryFeed("hidden_gem", 8),
    getDiscoveryFeed("new_release", 8),
    getDiscoveryFeed("just_analyzed", 6),
    getGenres(),
    getTagsGrouped(200),
    getCatalogStats(),
    getGenreInsights(FEATURED_REPORT_SLUG),
    // Single batched basics call powers the FeaturedReport game strip —
    // replaces the 9-call showcase fan-out that timed out under cold-start
    // Lambdas and ISR-cached an empty render.
    getGameBasics(SHOWCASE_GAMES.map((g) => g.appid)),
    // Single-call snapshot for the 4-card intelligence preview; partial
    // failure inside the endpoint nulls individual sub-blocks rather than
    // failing the whole render.
    getHomeIntelSnapshot(),
  ]);

  const featuredInsights =
    featuredReport.status === "fulfilled" ? featuredReport.value : null;
  const intelSnapshot =
    homeIntel.status === "fulfilled" ? homeIntel.value : null;

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
  const tagGroups: TagGroup[] = tags.status === "fulfilled" ? tags.value : [];

  const totalGames =
    catalogStats.status === "fulfilled" ? catalogStats.value.total_games : 0;

  // Repo preserves caller order; failure degrades to an empty strip and the
  // genre hero still renders.
  const strip: GameBasicsEntry[] =
    showcaseBasics.status === "fulfilled" ? showcaseBasics.value : [];

  const rows: {
    label: string;
    icon: React.ReactNode;
    games: Game[];
    seeAll: string;
  }[] = [
    {
      label: "Most Popular",
      icon: <TrendingUp className="w-4 h-4 text-teal" />,
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
      icon: <Sparkles className="w-4 h-4 text-teal" />,
      games: newGames,
      seeAll: "/search?sort=release_date",
    },
  ];

  const hasAnyGames = rows.some((r) => r.games.length > 0);

  return (
    <div className="min-h-screen bg-background">
      {/* Hero */}
      <header className="relative">
        <div
          className="absolute inset-0 opacity-30 pointer-events-none overflow-hidden"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(45,185,212,0.15), transparent)",
          }}
        />
        <div className="relative max-w-3xl mx-auto px-6 pt-20 pb-12 text-center">
          <h1
            className="font-serif text-h1 font-bold text-foreground mb-3 leading-tight"
            style={{ letterSpacing: "-0.03em" }}
          >
            Steam, decoded
          </h1>
          <p className="text-base text-muted-foreground mb-8 max-w-lg mx-auto">
            Player intelligence across 100,000+ Steam games. What players love.
            What they hate. What they want next.
          </p>
          <HeroSearch />
          {totalGames > 0 && genreList.length > 0 && (
            <ProofBar totalGames={totalGames} genreCount={genreList.length} />
          )}
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 pb-24 space-y-16">
        {/* Featured Report — genre synthesis CTA + 3-tab SEO-anchor strip */}
        {featuredInsights && (
          <FeaturedReport insights={featuredInsights} strip={strip} />
        )}

        {/* Universal intelligence preview — 4 cards, snapshot-driven */}
        {intelSnapshot && <IntelligenceCards snapshot={intelSnapshot} />}

        {/* Market Trends Preview */}
        <MarketTrendsPreview />

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
                <Clock className="w-4 h-4 text-teal" />
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

        {/* For Game Developers — Pro waitlist CTA */}
        <ForDevelopers />

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
        {tagGroups.length > 0 && <TagBrowser groups={tagGroups} />}

        {/* Footer CTA */}
        <FooterCTA />

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

// ISR: homepage content doesn't change faster than the matview refresh cadence.
// CloudFront + Next.js ISR serve the rendered HTML from cache for every visitor
// between revalidations. Individual apiFetch calls carry their own `revalidate`
// values and are honoured on re-render.
export const revalidate = 300;
