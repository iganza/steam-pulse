/**
 * Review display helper — picks the phase-appropriate count and sentiment for a
 * game based on its Early Access lifecycle.
 *
 * Post-EA (graduated) games should display POST-RELEASE counts to match Steam's
 * store UI ("No user reviews yet" when zero post-release reviews, even if the
 * game has many EA-era reviews). Pre-release / still-in-EA games fall back to
 * the all-time numbers. The backend denormalizes the split onto `games` at
 * review-ingest time (see migration 0048).
 *
 * Analytics views that intentionally show historical / all-time sentiment
 * (time-series, developer trajectory) should NOT use this helper.
 */
import type { Game } from "./types";

export type ReviewPhase = "post_release" | "early_access" | "all_time";

export interface DisplayedReview {
  count: number;
  positivePct: number;
  label: string;
  phase: ReviewPhase;
  /** True when the game has an EA history — callers render an "ex-EA" chip. */
  hasEarlyAccessHistory: boolean;
}

export function displayedReview(game: Game): DisplayedReview {
  const hasEA = !!game.has_early_access_reviews;
  const comingSoon = !!game.coming_soon;
  const postCount = game.review_count_post_release ?? 0;

  // Post-release: EA history AND released AND we have post-release reviews.
  if (hasEA && !comingSoon && postCount > 0) {
    return {
      count: postCount,
      positivePct: game.positive_pct_post_release ?? 0,
      label: game.review_score_desc_post_release ?? "",
      phase: "post_release",
      hasEarlyAccessHistory: true,
    };
  }

  // Early-access: still in EA, or graduated-out-of-EA with zero post-release.
  if (comingSoon || (hasEA && postCount === 0)) {
    return {
      count: game.review_count_english ?? game.review_count ?? 0,
      positivePct: game.positive_pct ?? 0,
      label: game.review_score_desc ?? "",
      phase: "early_access",
      hasEarlyAccessHistory: hasEA,
    };
  }

  // Default: game with no EA history — show all-time (current behavior).
  return {
    count: game.review_count_english ?? game.review_count ?? 0,
    positivePct: game.positive_pct ?? 0,
    label: game.review_score_desc ?? "",
    phase: "all_time",
    hasEarlyAccessHistory: false,
  };
}
