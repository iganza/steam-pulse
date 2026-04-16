/**
 * Review display helper — picks the phase-appropriate count and sentiment for a
 * game based on its Early Access lifecycle.
 *
 * Phase selection (matches the spec in scripts/prompts/split-ea-post-release-reviews.md):
 *  - `post_release`: game has EA history AND is released AND has ≥1 post-release review.
 *    Count/label come from the post-release split — this is what brings the card
 *    in line with Steam's store UI for ex-EA games.
 *  - `early_access`: game is coming soon, OR has EA history and released but
 *    zero post-release reviews. Counts fall back to the EA-era (all-time)
 *    numbers so users still see *something* — callers should label these as
 *    "Early Access reviews" and/or show the ex-EA indicator. (We deliberately
 *    do NOT render "No user reviews yet" here — the all-time numbers are
 *    accurate EA reviews, they are not absent.)
 *  - `all_time`: game with no EA history — current behavior.
 *
 * `hasEarlyAccessHistory` is exposed independently of phase so callers can
 * render an ex-EA chip for BOTH post_release and early_access phases of an
 * ex-EA game. Analytics views (time-series, dev trajectory) should not use
 * this helper — they want raw all-time numbers.
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
