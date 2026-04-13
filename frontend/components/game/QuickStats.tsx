"use client";

import Link from "next/link";
import { BarChart3, Calendar, Clock, DollarSign, Zap } from "lucide-react";
import { SectionLabel } from "@/components/game/SectionLabel";
import { relativeTime } from "@/lib/format";
import type { ReviewStats } from "@/lib/types";

interface QuickStatsProps {
  /** Steam's total review count — shown in the Reviews tile when there's
   *  no analyzed count to prefer. */
  reviewCount: number | null;
  /** LLM-ingested English review count. When non-null it takes precedence
   *  over `reviewCount` in the Reviews tile and shows an "en" suffix. */
  totalReviewsAnalyzed: number | null;
  releaseDate?: string;
  price: string;
  /** Non-null when the game has been analyzed. Triggers the extra "Analyzed"
   *  tile and bumps the grid from 4 columns to 5. */
  lastAnalyzed: string | null;
  reviewStats: ReviewStats | null;
  statsLoading: boolean;
  reviewCrawledAt?: string | null;
  reviewsCompletedAt?: string | null;
  metaCrawledAt?: string | null;
}

function momentumLabel(
  reviewsLast30: number,
  reviewsPerDay: number,
): { label: string; color: string } {
  const expected = reviewsPerDay * 30;
  if (expected <= 0) return { label: "—", color: "var(--muted-foreground)" };
  const ratio = reviewsLast30 / expected;
  if (ratio >= 1.2) return { label: "Gaining momentum", color: "#22c55e" };
  if (ratio >= 0.8) return { label: "Steady", color: "var(--muted-foreground)" };
  return { label: "Slowing", color: "#f59e0b" };
}

const TILE_CLASS = "p-4 rounded-xl";
const TILE_STYLE = {
  background: "var(--card)",
  border: "1px solid var(--border)",
} as const;

export function QuickStats({
  reviewCount,
  totalReviewsAnalyzed,
  releaseDate,
  price,
  lastAnalyzed,
  reviewStats,
  statsLoading,
  reviewCrawledAt,
  reviewsCompletedAt,
  metaCrawledAt,
}: QuickStatsProps) {
  const reviewsValue = totalReviewsAnalyzed ?? reviewCount;
  const showEnSuffix = totalReviewsAnalyzed != null;
  const reviewsTs = relativeTime(reviewCrawledAt) ?? relativeTime(reviewsCompletedAt);
  const metaTs = relativeTime(metaCrawledAt);
  // Tiles: Reviews + Released + Price + Velocity = 4 base, +1 when analyzed.
  // Developer/Publisher credits moved into <GameHero /> as inline text so the
  // tile grid stays numeric-only and never squishes on long studio names.
  const gridClass = lastAnalyzed
    ? "grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4"
    : "grid grid-cols-2 md:grid-cols-4 gap-4";

  return (
    <section className="animate-fade-up stagger-2">
      <SectionLabel>Quick Stats</SectionLabel>
      <div className={gridClass}>
        {/* Reviews */}
        <div className={TILE_CLASS} style={TILE_STYLE}>
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <BarChart3 className="w-4 h-4" />
            <span className="text-sm uppercase tracking-widest font-mono">Reviews</span>
          </div>
          <p className="font-mono text-base font-medium truncate">
            {reviewsValue?.toLocaleString() ?? "—"}
            {showEnSuffix && reviewsValue != null && (
              <span
                className="font-mono"
                style={{ opacity: 0.4, fontSize: "0.7em", marginLeft: "0.3em" }}
              >
                en
              </span>
            )}
          </p>
          {reviewsTs && (
            <p
              data-testid="reviews-tile-crawled"
              className="text-xs font-mono text-muted-foreground mt-1"
            >
              Crawled {reviewsTs}
            </p>
          )}
        </div>
        {/* Released */}
        <div className={TILE_CLASS} style={TILE_STYLE}>
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Calendar className="w-4 h-4" />
            <span className="text-sm uppercase tracking-widest font-mono">Released</span>
          </div>
          {releaseDate ? (
            <Link
              href={`/search?year_from=${new Date(releaseDate).getFullYear()}&year_to=${new Date(releaseDate).getFullYear()}`}
              className="font-mono text-base font-medium hover:underline"
              style={{ color: "var(--teal)" }}
            >
              {new Date(releaseDate).getFullYear()}
            </Link>
          ) : (
            <p className="font-mono text-base font-medium">—</p>
          )}
        </div>
        {/* Price */}
        <div className={TILE_CLASS} style={TILE_STYLE}>
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <DollarSign className="w-4 h-4" />
            <span className="text-sm uppercase tracking-widest font-mono">Price</span>
          </div>
          <p className="font-mono text-base font-medium truncate">{price}</p>
        </div>
        {/* Analyzed — only when the game has a report */}
        {lastAnalyzed && (
          <div className={TILE_CLASS} style={TILE_STYLE}>
            <div className="flex items-center gap-2 text-muted-foreground mb-2">
              <Clock className="w-4 h-4" />
              <span className="text-sm uppercase tracking-widest font-mono">Analyzed</span>
            </div>
            <p className="font-mono text-base font-medium truncate">
              {new Date(lastAnalyzed).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          </div>
        )}
        {/* Velocity */}
        <div className={TILE_CLASS} style={TILE_STYLE}>
          <div className="flex items-center gap-2 text-muted-foreground mb-2">
            <Zap className="w-4 h-4" />
            <span className="text-sm uppercase tracking-widest font-mono">Velocity</span>
          </div>
          {statsLoading ? (
            <div className="h-4 bg-secondary rounded animate-pulse w-20" />
          ) : reviewStats ? (
            <>
              <p className="font-mono text-base font-medium">
                {reviewStats.review_velocity.reviews_per_day}/day
              </p>
              {(() => {
                const m = momentumLabel(
                  reviewStats.review_velocity.reviews_last_30_days,
                  reviewStats.review_velocity.reviews_per_day,
                );
                return (
                  <p className="text-sm font-mono mt-1" style={{ color: m.color }}>
                    {m.label}
                  </p>
                );
              })()}
            </>
          ) : (
            <p className="font-mono text-base font-medium">—</p>
          )}
        </div>
      </div>
      {metaTs && (
        <p
          data-testid="quick-stats-meta-updated"
          className="mt-3 text-xs font-mono text-muted-foreground"
        >
          Page metadata updated {metaTs} · Source: Steam
        </p>
      )}
    </section>
  );
}
