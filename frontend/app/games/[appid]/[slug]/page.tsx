import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getGameReport, getRelatedAnalyzedGames } from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { RelatedAnalyzedGame } from "@/lib/types";
import { GameReportClient } from "./GameReportClient";

interface Props {
  params: Promise<{ appid: string; slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { appid, slug } = await params;
  const numericAppid = Number(appid);
  const fallbackImage = `https://cdn.akamai.steamstatic.com/steam/apps/${numericAppid}/header.jpg`;
  const canonicalUrl = `https://steampulse.io/games/${appid}/${slug}`;

  try {
    const reportData = await getGameReport(numericAppid);
    const headerImage = reportData.game?.header_image ?? fallbackImage;
    if (reportData.status === "available" && reportData.report) {
      const report = reportData.report;
      return {
        title: `${report.game_name} Reviews & Analysis`,
        description: report.one_liner,
        openGraph: {
          title: `${report.game_name} Reviews & Analysis — SteamPulse`,
          description: report.one_liner,
          images: [{ url: headerImage }],
          url: canonicalUrl,
          type: "article",
        },
        twitter: {
          card: "summary_large_image",
          title: `${report.game_name} Reviews & Analysis — SteamPulse`,
          description: report.one_liner,
          images: [headerImage],
        },
        alternates: { canonical: canonicalUrl },
      };
    }
    // No report — use game metadata from the same response
    if (reportData.game) {
      const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      const desc = reportData.game.short_desc ?? `Steam game — ${name}`;
      return {
        title: `${name} — SteamPulse`,
        description: desc,
        openGraph: {
          title: `${name} — SteamPulse`,
          description: desc,
          images: [{ url: headerImage }],
          url: canonicalUrl,
          type: "article",
        },
        twitter: {
          card: "summary_large_image",
          title: `${name} — SteamPulse`,
          description: desc,
          images: [headerImage],
        },
        alternates: { canonical: canonicalUrl },
      };
    }
  } catch {
    // fall through
  }

  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} — SteamPulse`,
    description: `Steam game — ${name}`,
    alternates: { canonical: canonicalUrl },
  };
}

export default async function GameReportPage({ params }: Props) {
  const { appid, slug } = await params;
  const numericAppid = Number(appid);

  if (!numericAppid || isNaN(numericAppid)) notFound();

  const fallbackImage = `https://cdn.akamai.steamstatic.com/steam/apps/${numericAppid}/header.jpg`;

  let report = null;
  let headerImage = fallbackImage;
  let gameData: {
    gameName?: string;
    releaseDate?: string;
    developer?: string;
    developerSlug?: string;
    publisher?: string;
    publisherSlug?: string;
    priceUsd?: number | null;
    isFree?: boolean;
    genres?: string[];
    tags?: string[];
    shortDesc?: string;
    reviewCount?: number;
    deckCompatibility?: number | null;
    deckTestResults?: Array<{ display_type: number; loc_token: string }>;
    isEarlyAccess?: boolean;
    // Steam-sourced sentiment + freshness — surfaced in the Steam Facts zone
    positivePct?: number | null;
    reviewScoreDesc?: string | null;
    metaCrawledAt?: string | null;
    reviewCrawledAt?: string | null;
    reviewsCompletedAt?: string | null;
    tagsCrawledAt?: string | null;
    lastAnalyzed?: string | null;
    estimatedOwners?: number | null;
    estimatedRevenueUsd?: number | null;
    revenueEstimateMethod?: string | null;
    revenueEstimateReason?: string | null;
  } = {};

  try {
    const reportData = await getGameReport(numericAppid);
    if (reportData.status === "available" && reportData.report) {
      report = reportData.report;
    }
    if (reportData.game) {
      const g = reportData.game;
      if (g.name) gameData.gameName = g.name;
      if (g.header_image) headerImage = g.header_image;
      if (g.short_desc) gameData.shortDesc = g.short_desc;
      if (g.developer) gameData.developer = g.developer;
      if (g.developer_slug) gameData.developerSlug = g.developer_slug;
      if (g.publisher) gameData.publisher = g.publisher;
      if (g.publisher_slug) gameData.publisherSlug = g.publisher_slug;
      if (g.release_date) gameData.releaseDate = g.release_date;
      if (g.price_usd != null) gameData.priceUsd = g.price_usd;
      if (g.is_free != null) gameData.isFree = g.is_free;
      if (g.genres?.length) gameData.genres = g.genres;
      if (g.tags?.length) gameData.tags = g.tags;
      if (g.deck_compatibility != null) gameData.deckCompatibility = g.deck_compatibility;
      if (g.deck_test_results?.length) gameData.deckTestResults = g.deck_test_results;
      if (g.is_early_access != null) gameData.isEarlyAccess = g.is_early_access;
      // Steam-sourced sentiment + freshness fields — wired through to the client.
      // Always prefer review_count_english so the number next to positive_pct /
      // review_score_desc stays on the same English-implicit basis; fall back
      // to all-language review_count only when no English count exists (keeps
      // QuickStats' Reviews tile and MarketReach's X/50 empty state populated).
      if (g.positive_pct != null) gameData.positivePct = g.positive_pct;
      if (g.review_score_desc != null) gameData.reviewScoreDesc = g.review_score_desc;
      const englishAlignedCount = g.review_count_english ?? g.review_count;
      if (englishAlignedCount != null) gameData.reviewCount = englishAlignedCount;
      if (g.meta_crawled_at) gameData.metaCrawledAt = g.meta_crawled_at;
      if (g.review_crawled_at) gameData.reviewCrawledAt = g.review_crawled_at;
      if (g.reviews_completed_at) gameData.reviewsCompletedAt = g.reviews_completed_at;
      if (g.tags_crawled_at) gameData.tagsCrawledAt = g.tags_crawled_at;
      if (g.last_analyzed) gameData.lastAnalyzed = g.last_analyzed;
      // Boxleiter v1 revenue estimate fields — forwarded to <MarketReach />
      if (g.estimated_owners != null) gameData.estimatedOwners = g.estimated_owners;
      if (g.estimated_revenue_usd != null) gameData.estimatedRevenueUsd = g.estimated_revenue_usd;
      if (g.revenue_estimate_method) gameData.revenueEstimateMethod = g.revenue_estimate_method;
      if (g.revenue_estimate_reason) gameData.revenueEstimateReason = g.revenue_estimate_reason;
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    if (!(err instanceof ApiError)) throw err;
  }

  if (!gameData.gameName) {
    gameData.gameName = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // Un-analyzed pages surface up to 6 analyzed neighbors so SEO visitors
  // always have a path to a full report. Skipped on analyzed pages — the
  // report itself is the destination.
  let relatedAnalyzed: RelatedAnalyzedGame[] = [];
  if (!report) {
    try {
      const related = await getRelatedAnalyzedGames(numericAppid);
      relatedAnalyzed = related.games;
    } catch {
      // Related list is non-critical — a failure just hides the section.
    }
  }

  // Build JSON-LD structured data
  const canonicalUrl = `https://steampulse.io/games/${appid}/${slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "VideoGame",
    "name": report?.game_name ?? gameData.gameName ?? "Unknown Game",
    "image": headerImage,
    "url": canonicalUrl,
    "gamePlatform": "PC",
    "applicationCategory": "Game",
    ...(gameData.genres?.length ? { "genre": gameData.genres } : {}),
    ...(gameData.releaseDate ? { "datePublished": gameData.releaseDate } : {}),
    "operatingSystem": "Windows",
    ...(report?.one_liner
      ? { "description": report.one_liner }
      : gameData.shortDesc
        ? { "description": gameData.shortDesc }
        : {}),
    ...(gameData.reviewCount != null
      ? { "numberOfPlayers": { "@type": "QuantitativeValue", "value": gameData.reviewCount } }
      : {}),
    // aggregateRating is sourced from Steam's positive_pct (canonical) — never
    // from the LLM. Only emitted when both the percentage and a meaningful
    // review count are available.
    ...(gameData.positivePct != null && (gameData.reviewCount ?? 0) > 0
      ? {
          "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": (gameData.positivePct / 10).toFixed(1),
            "bestRating": "10",
            "worstRating": "0",
            "ratingCount": String(gameData.reviewCount ?? 0),
          },
        }
      : {}),
    // author/publisher from Steam metadata — populated even without an LLM
    // report so no-report pages still emit full schema. Linked to the
    // respective entity pages via a URL when we have a slug.
    ...(gameData.developer
      ? {
          "author": {
            "@type": "Organization",
            "name": gameData.developer,
            ...(gameData.developerSlug
              ? { "url": `https://steampulse.io/developer/${gameData.developerSlug}` }
              : {}),
          },
        }
      : {}),
    ...(gameData.publisher
      ? {
          "publisher": {
            "@type": "Organization",
            "name": gameData.publisher,
            ...(gameData.publisherSlug
              ? { "url": `https://steampulse.io/publisher/${gameData.publisherSlug}` }
              : {}),
          },
        }
      : {}),
    // Offer — price + currency. Free games emit "0" so crawlers still see a
    // valid Offer; paid games emit the USD price. Link points to the Steam
    // store page, the canonical purchase location.
    ...(gameData.isFree || gameData.priceUsd != null
      ? {
          "offers": {
            "@type": "Offer",
            "price": gameData.isFree ? "0" : gameData.priceUsd!.toFixed(2),
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
            "url": `https://store.steampowered.com/app/${numericAppid}`,
          },
        }
      : {}),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main>
        <GameReportClient
          report={report}
          appid={numericAppid}
          gameName={gameData.gameName}
          headerImage={headerImage}
          releaseDate={gameData.releaseDate}
          developer={gameData.developer}
          developerSlug={gameData.developerSlug}
          publisher={gameData.publisher}
          publisherSlug={gameData.publisherSlug}
          priceUsd={gameData.priceUsd}
          isFree={gameData.isFree ?? false}
          genres={gameData.genres ?? []}
          tags={gameData.tags ?? []}
          shortDesc={gameData.shortDesc}
          reviewCount={gameData.reviewCount}
          deckCompatibility={gameData.deckCompatibility}
          deckTestResults={gameData.deckTestResults}
          isEarlyAccess={gameData.isEarlyAccess}
          positivePct={gameData.positivePct}
          reviewScoreDesc={gameData.reviewScoreDesc}
          metaCrawledAt={gameData.metaCrawledAt}
          reviewCrawledAt={gameData.reviewCrawledAt}
          reviewsCompletedAt={gameData.reviewsCompletedAt}
          tagsCrawledAt={gameData.tagsCrawledAt}
          lastAnalyzed={gameData.lastAnalyzed}
          estimatedOwners={gameData.estimatedOwners}
          estimatedRevenueUsd={gameData.estimatedRevenueUsd}
          revenueEstimateMethod={gameData.revenueEstimateMethod}
          revenueEstimateReason={gameData.revenueEstimateReason}
          relatedAnalyzed={relatedAnalyzed}
        />
      </main>
    </>
  );
}

// ISR: revalidate every 24 hours
export const revalidate = 86400;
