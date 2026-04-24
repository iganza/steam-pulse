import type { Metadata } from "next";
import Link from "next/link";
import { Gem, TrendingUp, ChevronRight, Star, Sparkles, Clock } from "lucide-react";
import { HeroSearch } from "@/components/layout/HeroSearch";
import {
  getDiscoveryFeed,
  getCatalogStats,
  getGenres,
  getTagsGrouped,
  getGameReport,
  getReviewStats,
  getAudienceOverlap,
  getAnalyticsTrendSentiment,
  getGenreInsights,
} from "@/lib/api";
import { TagBrowser } from "@/components/home/TagBrowser";
import { ProofBar } from "@/components/home/ProofBar";
import { FeaturedReport } from "@/components/home/FeaturedReport";
import { IntelligenceCards } from "@/components/home/IntelligenceCards";
import { GameShowcase } from "@/components/home/GameShowcase";
import type { ShowcaseGame } from "@/components/home/GameShowcase";
import { MarketTrendsPreview } from "@/components/home/MarketTrendsPreview";
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
    // Showcase game 1: Baldur's Gate 3
    sc0Report, sc0Stats, sc0Overlap,
    // Showcase game 2: Stardew Valley
    sc1Report, sc1Stats, sc1Overlap,
    // Showcase game 3: Cyberpunk 2077
    sc2Report, sc2Stats, sc2Overlap,
    trendSentiment,
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
    // Per-game showcase fetches (3 games × 3 endpoints = 9 calls)
    getGameReport(SHOWCASE_GAMES[0].appid),
    getReviewStats(SHOWCASE_GAMES[0].appid),
    getAudienceOverlap(SHOWCASE_GAMES[0].appid, 5),
    getGameReport(SHOWCASE_GAMES[1].appid),
    getReviewStats(SHOWCASE_GAMES[1].appid),
    getAudienceOverlap(SHOWCASE_GAMES[1].appid, 5),
    getGameReport(SHOWCASE_GAMES[2].appid),
    getReviewStats(SHOWCASE_GAMES[2].appid),
    getAudienceOverlap(SHOWCASE_GAMES[2].appid, 5),
    getAnalyticsTrendSentiment({ granularity: "month", limit: 12 }),
  ]);

  const featuredInsights =
    featuredReport.status === "fulfilled" ? featuredReport.value : null;

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

  // Showcase data — assemble per-game, skip any that failed
  const scResults = [
    { report: sc0Report, stats: sc0Stats, overlap: sc0Overlap, ...SHOWCASE_GAMES[0] },
    { report: sc1Report, stats: sc1Stats, overlap: sc1Overlap, ...SHOWCASE_GAMES[1] },
    { report: sc2Report, stats: sc2Stats, overlap: sc2Overlap, ...SHOWCASE_GAMES[2] },
  ];

  const showcaseGames: ShowcaseGame[] = scResults
    .filter(
      (sc) =>
        sc.report.status === "fulfilled" &&
        sc.report.value.report &&
        sc.report.value.game,
    )
    .map((sc) => {
      const r = (sc.report as PromiseFulfilledResult<Awaited<ReturnType<typeof getGameReport>>>).value;
      const s = sc.stats.status === "fulfilled" ? sc.stats.value : null;
      const o = sc.overlap.status === "fulfilled" ? sc.overlap.value : null;
      return {
        appid: sc.appid,
        slug: sc.slug,
        gameName: r.report!.game_name,
        headerImage: r.game?.header_image || `https://cdn.akamai.steamstatic.com/steam/apps/${sc.appid}/header.jpg`,
        report: r.report!,
        timeline: s?.timeline ?? [],
        overlaps: o?.overlaps ?? [],
        totalReviewers: o?.total_reviewers ?? 0,
      };
    });

  const sentimentTrend =
    trendSentiment.status === "fulfilled"
      ? trendSentiment.value.periods
      : [];

  const hasIntelCards = showcaseGames.length > 0;

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
            className="font-serif text-4xl md:text-5xl font-bold text-foreground mb-3 leading-tight"
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
        {/* Featured Report — primary CTA pointing at the live genre synthesis page */}
        {featuredInsights && <FeaturedReport insights={featuredInsights} />}

        {/* Intelligence Preview Cards */}
        {hasIntelCards && showcaseGames.length > 0 && (
          <IntelligenceCards
            timeline={showcaseGames[0].timeline}
            overlaps={showcaseGames[0].overlaps}
            trendData={sentimentTrend}
            report={showcaseGames[0].report}
          />
        )}

        {/* Game Intelligence Showcase — tabbed, up to 3 games */}
        {showcaseGames.length > 0 && (
          <GameShowcase games={showcaseGames} />
        )}

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
