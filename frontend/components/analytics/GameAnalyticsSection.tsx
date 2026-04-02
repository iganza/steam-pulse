"use client";

import { useState, useEffect, useCallback } from "react";
import { usePro } from "@/lib/pro";
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
  const isPro = usePro();
  const [overlap, setOverlap] = useState<AudienceOverlap | null>(null);
  const [playtimeSentiment, setPlaytimeSentiment] = useState<PlaytimeSentiment | null>(null);
  const [eaImpact, setEaImpact] = useState<EarlyAccessImpact | null>(null);
  const [velocity, setVelocity] = useState<ReviewVelocity | null>(null);
  const [topReviews, setTopReviews] = useState<TopReviewsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      const results = await Promise.allSettled([
        getAudienceOverlap(appid, isPro ? 20 : 5),
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

  const hasData = overlap || playtimeSentiment || eaImpact || velocity || topReviews;

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
      {playtimeSentiment && <PlaytimeSentimentChart data={playtimeSentiment} />}
      {velocity && <ReviewVelocityChart data={velocity} />}
      {eaImpact && <EarlyAccessImpactChart data={eaImpact} />}
      {topReviews && <TopReviews data={topReviews} onSortChange={handleSortChange} />}
      {overlap && (
        <AudienceOverlapChart data={overlap} gameName={gameName} showAll={isPro} />
      )}
    </div>
  );
}
