"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getAudienceOverlap,
  getPlaytimeSentiment,
  getEarlyAccessImpact,
  getReviewVelocity,
  getTopReviews,
} from "@/lib/api";
import type {
  AudienceOverlap,
  PlaytimeSentiment,
  EarlyAccessImpact,
  ReviewVelocity,
  TopReviewsResponse,
} from "@/lib/types";
import { PlaytimeSentimentChart } from "@/components/analytics/PlaytimeSentimentChart";
import { ReviewVelocityChart } from "@/components/analytics/ReviewVelocityChart";
import { EarlyAccessImpact as EarlyAccessImpactChart } from "@/components/analytics/EarlyAccessImpact";
import { TopReviews } from "@/components/analytics/TopReviews";
import { AudienceOverlap as AudienceOverlapChart } from "@/components/analytics/AudienceOverlap";

interface GameAnalyticsSectionProps {
  appid: number;
  gameName: string;
}

export function GameAnalyticsSection({ appid, gameName }: GameAnalyticsSectionProps) {
  const [overlap, setOverlap] = useState<AudienceOverlap | null>(null);
  const [playtimeSentiment, setPlaytimeSentiment] = useState<PlaytimeSentiment | null>(null);
  const [eaImpact, setEaImpact] = useState<EarlyAccessImpact | null>(null);
  const [velocity, setVelocity] = useState<ReviewVelocity | null>(null);
  const [topReviews, setTopReviews] = useState<TopReviewsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setOverlap(null);
    setPlaytimeSentiment(null);
    setEaImpact(null);
    setVelocity(null);
    setTopReviews(null);

    async function fetchAll() {
      const results = await Promise.allSettled([
        getAudienceOverlap(appid, 20),
        getPlaytimeSentiment(appid),
        getEarlyAccessImpact(appid),
        getReviewVelocity(appid),
        getTopReviews(appid),
      ]);

      if (cancelled) return;

      setOverlap(results[0].status === "fulfilled" ? results[0].value : null);
      setPlaytimeSentiment(results[1].status === "fulfilled" ? results[1].value : null);
      setEaImpact(results[2].status === "fulfilled" ? results[2].value : null);
      setVelocity(results[3].status === "fulfilled" ? results[3].value : null);
      setTopReviews(results[4].status === "fulfilled" ? results[4].value : null);
      setLoading(false);
    }

    fetchAll();
    return () => { cancelled = true; };
  }, [appid]);

  const handleSortChange = useCallback(
    async (sort: "helpful" | "funny") => {
      try {
        const data = await getTopReviews(appid, sort);
        setTopReviews(data);
      } catch {
        // keep existing data on error
      }
    },
    [appid],
  );

  // Inspect meaningful content — not just "endpoint returned an object" —
  // so a game with all-empty payloads (the soft-launch thin no-report case)
  // collapses the entire "Deep Dive Analytics" block rather than rendering
  // an empty label with no child cards.
  const hasOverlap = (overlap?.overlaps.length ?? 0) > 0;
  const hasPlaytime = (playtimeSentiment?.buckets.length ?? 0) > 0;
  // Mirror EarlyAccessImpact's own render guard exactly
  // (verdict !== "no_ea" && early_access != null && post_launch != null) so
  // hasData can't diverge from what the card itself would render — e.g. a
  // "no_post" verdict with post_launch null would otherwise flip hasData
  // true while the card rendered nothing.
  const hasEA =
    eaImpact != null &&
    eaImpact.verdict !== "no_ea" &&
    eaImpact.early_access != null &&
    eaImpact.post_launch != null;
  const hasVelocity = (velocity?.monthly.length ?? 0) >= 2;
  const hasTopReviews = (topReviews?.reviews.length ?? 0) > 0;
  const hasData = hasOverlap || hasPlaytime || hasEA || hasVelocity || hasTopReviews;

  if (loading) {
    return (
      <p className="text-base text-muted-foreground font-mono py-8">
        Loading analytics...
      </p>
    );
  }

  if (!hasData) return null;

  return (
    <div className="space-y-6">
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
        Deep Dive Analytics
      </p>
      {hasPlaytime && <PlaytimeSentimentChart data={playtimeSentiment!} />}
      {hasVelocity && <ReviewVelocityChart data={velocity!} />}
      {hasEA && <EarlyAccessImpactChart data={eaImpact!} />}
      {hasTopReviews && (
        <TopReviews data={topReviews!} onSortChange={handleSortChange} />
      )}
      {hasOverlap && (
        <AudienceOverlapChart data={overlap!} gameName={gameName} />
      )}
    </div>
  );
}
