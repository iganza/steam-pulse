"use client";

import { ScoreBar } from "@/components/game/ScoreBar";
import { relativeTime } from "@/lib/format";

interface SteamFactsCardProps {
  positivePct: number | null;
  reviewScoreDesc: string | null;
  reviewCrawledAt?: string | null;
  reviewsCompletedAt?: string | null;
  metaCrawledAt?: string | null;
}

// Steam sentiment magnitude is Steam-owned — NEVER derived from the LLM.
// Rendered on both analyzed and unanalyzed pages so users always see the
// canonical Steam sentiment context.
function scoreContextSentence(score: number): string {
  if (score >= 95)
    return "Overwhelmingly Positive — fewer than 5% of Steam games with 1,000+ reviews achieve this.";
  if (score >= 80)
    return "Very Positive — this puts the game in the top 30% of all reviewed games on Steam.";
  if (score >= 70) return "Mostly Positive — above the median for reviewed Steam games.";
  if (score >= 50) return "Mixed — roughly half of players recommend it.";
  return "Mostly Negative — significant player dissatisfaction.";
}

export function SteamFactsCard({
  positivePct,
  reviewScoreDesc,
  reviewCrawledAt,
  reviewsCompletedAt,
  metaCrawledAt,
}: SteamFactsCardProps) {
  const crawledAt =
    relativeTime(reviewCrawledAt) ??
    relativeTime(reviewsCompletedAt) ??
    relativeTime(metaCrawledAt);

  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between mb-3 text-xs font-mono uppercase tracking-widest text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden>👍</span>
          Steam Facts
        </span>
        {crawledAt && <span data-testid="steam-facts-crawled">Crawled {crawledAt}</span>}
      </div>
      {positivePct != null ? (
        <ScoreBar score={positivePct} label={reviewScoreDesc ?? undefined} />
      ) : (
        <p className="text-sm text-muted-foreground font-mono">
          Steam sentiment unavailable for this game.
        </p>
      )}
      {positivePct != null && (
        <p
          className="mt-2 text-sm text-muted-foreground font-mono"
          data-testid="score-context"
        >
          {scoreContextSentence(positivePct)}
        </p>
      )}
    </div>
  );
}
