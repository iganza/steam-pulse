import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getGameReport } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { Suspense } from "react";
import { GameReportClient } from "./GameReportClient";
import { ToolkitShell } from "@/components/toolkit/ToolkitShell";

interface Props {
  params: Promise<{ appid: string; slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { appid, slug } = await params;
  const numericAppid = Number(appid);
  const headerImage = `https://cdn.akamai.steamstatic.com/steam/apps/${numericAppid}/header.jpg`;
  const canonicalUrl = `https://steampulse.io/games/${appid}/${slug}`;

  try {
    const reportData = await getGameReport(numericAppid);
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

  const headerImage = `https://cdn.akamai.steamstatic.com/steam/apps/${numericAppid}/header.jpg`;

  let report = null;
  let gameData: {
    gameName?: string;
    releaseDate?: string;
    developer?: string;
    priceUsd?: number | null;
    isFree?: boolean;
    genres?: string[];
    tags?: string[];
    shortDesc?: string;
    reviewCount?: number;
    deckCompatibility?: number | null;
    deckTestResults?: Array<{ display_type: number; loc_token: string }>;
    isEarlyAccess?: boolean;
  } = {};

  try {
    const reportData = await getGameReport(numericAppid);
    if (reportData.status === "available" && reportData.report) {
      report = reportData.report;
    }
    if (reportData.review_count) {
      gameData.reviewCount = reportData.review_count;
    }
    if (reportData.game) {
      const g = reportData.game;
      if (g.short_desc) gameData.shortDesc = g.short_desc;
      if (g.developer) gameData.developer = g.developer;
      if (g.release_date) gameData.releaseDate = g.release_date;
      if (g.price_usd != null) gameData.priceUsd = g.price_usd;
      if (g.is_free != null) gameData.isFree = g.is_free;
      if (g.genres?.length) gameData.genres = g.genres;
      if (g.tags?.length) gameData.tags = g.tags;
      if (g.deck_compatibility != null) gameData.deckCompatibility = g.deck_compatibility;
      if (g.deck_test_results?.length) gameData.deckTestResults = g.deck_test_results;
      if (g.is_early_access != null) gameData.isEarlyAccess = g.is_early_access;
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    if (!(err instanceof ApiError)) throw err;
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
    ...(report ? {
      "aggregateRating": {
        "@type": "AggregateRating",
        "ratingValue": ((report.sentiment_score / 10).toFixed(1)),
        "bestRating": "10",
        "worstRating": "0",
        "ratingCount": String(report.total_reviews_analyzed ?? 0),
      },
    } : {}),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main>
        <Suspense
          fallback={
            <GameReportClient
              report={report}
              appid={numericAppid}
              gameName={gameData.gameName}
              headerImage={headerImage}
              releaseDate={gameData.releaseDate}
              developer={gameData.developer}
              priceUsd={gameData.priceUsd}
              isFree={gameData.isFree ?? false}
              genres={gameData.genres ?? []}
              tags={gameData.tags ?? []}
              shortDesc={gameData.shortDesc}
              reviewCount={gameData.reviewCount}
              deckCompatibility={gameData.deckCompatibility}
              deckTestResults={gameData.deckTestResults}
              isEarlyAccess={gameData.isEarlyAccess}
            />
          }
        >
          <ToolkitShell
            lockedFilters={{ appids: [numericAppid] }}
            defaultLens="sentiment"
            visibleLenses={["sentiment", "compare", "benchmark"]}
            lensContent={{
              sentiment: (
                <GameReportClient
                  report={report}
                  appid={numericAppid}
                  gameName={gameData.gameName}
                  headerImage={headerImage}
                  releaseDate={gameData.releaseDate}
                  developer={gameData.developer}
                  priceUsd={gameData.priceUsd}
                  isFree={gameData.isFree ?? false}
                  genres={gameData.genres ?? []}
                  tags={gameData.tags ?? []}
                  shortDesc={gameData.shortDesc}
                  reviewCount={gameData.reviewCount}
                  deckCompatibility={gameData.deckCompatibility}
                  deckTestResults={gameData.deckTestResults}
                  isEarlyAccess={gameData.isEarlyAccess}
                />
              ),
            }}
          />
        </Suspense>
      </main>
    </>
  );
}

// ISR: revalidate every 24 hours
export const revalidate = 86400;
