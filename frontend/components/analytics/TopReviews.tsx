"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { TopReviewsResponse, TopReview } from "@/lib/types";

interface TopReviewsProps {
  data: TopReviewsResponse;
  onSortChange?: (sort: "helpful" | "funny") => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function ReviewCard({ review }: { review: TopReview }) {
  return (
    <div
      className="flex gap-3 rounded-lg p-3"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <div className="flex-shrink-0 text-xl mt-0.5">
        {review.voted_up ? (
          <span style={{ color: "#22c55e" }} title="Recommended" aria-label="Thumbs up">&#x1F44D;</span>
        ) : (
          <span style={{ color: "#ef4444" }} title="Not Recommended" aria-label="Thumbs down">&#x1F44E;</span>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm leading-relaxed line-clamp-3">{review.body_preview}</p>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono">{review.playtime_hours != null ? `${review.playtime_hours}h` : "\u2014"} played</span>
          <span>&middot;</span>
          <span>{review.votes_helpful.toLocaleString()} helpful</span>
          <span>&middot;</span>
          <span>{review.votes_funny.toLocaleString()} funny</span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {review.written_during_early_access && (
            <span
              className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: "rgba(59,130,246,0.15)", color: "#3b82f6" }}
            >
              Early Access
            </span>
          )}
          {review.received_for_free && (
            <span
              className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: "rgba(107,114,128,0.15)", color: "#6b7280" }}
            >
              Free Key
            </span>
          )}
          <span className="text-xs text-muted-foreground ml-auto">{formatDate(review.posted_at)}</span>
        </div>
      </div>
    </div>
  );
}

export function TopReviews({ data, onSortChange }: TopReviewsProps) {
  if (data.reviews.length === 0) return null;

  const activeSort = data.sort as "helpful" | "funny";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Top Reviews</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex gap-2 mb-4">
          <button
            type="button"
            onClick={() => onSortChange?.("helpful")}
            className="text-xs font-medium px-3 py-1.5 rounded-full transition-colors"
            style={
              activeSort === "helpful"
                ? { background: "var(--teal)", color: "#fff" }
                : { background: "var(--border)", color: "var(--muted-foreground)" }
            }
          >
            Most Helpful
          </button>
          <button
            type="button"
            onClick={() => onSortChange?.("funny")}
            className="text-xs font-medium px-3 py-1.5 rounded-full transition-colors"
            style={
              activeSort === "funny"
                ? { background: "var(--teal)", color: "#fff" }
                : { background: "var(--border)", color: "var(--muted-foreground)" }
            }
          >
            Most Funny
          </button>
        </div>

        <div className="flex flex-col gap-3">
          {data.reviews.map((review) => (
            <ReviewCard key={review.steam_review_id} review={review} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
