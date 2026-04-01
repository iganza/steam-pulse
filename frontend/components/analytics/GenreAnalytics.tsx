"use client";

import { useState, useEffect } from "react";
import {
  getPricePositioning,
  getReleaseTiming,
  getPlatformGaps,
} from "@/lib/api";
import type {
  PricePositioning,
  ReleaseTiming,
  PlatformGaps,
} from "@/lib/types";
import { PricePositioning as PricePositioningChart } from "@/components/analytics/PricePositioning";
import { ReleaseTiming as ReleaseTimingChart } from "@/components/analytics/ReleaseTiming";
import { PlatformGaps as PlatformGapsChart } from "@/components/analytics/PlatformGaps";

interface GenreAnalyticsProps {
  slug: string;
}

export function GenreAnalytics({ slug }: GenreAnalyticsProps) {
  const [pricing, setPricing] = useState<PricePositioning | null>(null);
  const [timing, setTiming] = useState<ReleaseTiming | null>(null);
  const [platforms, setPlatforms] = useState<PlatformGaps | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      const results = await Promise.allSettled([
        getPricePositioning(slug),
        getReleaseTiming(slug),
        getPlatformGaps(slug),
      ]);

      if (cancelled) return;

      setPricing(results[0].status === "fulfilled" ? results[0].value : null);
      setTiming(results[1].status === "fulfilled" ? results[1].value : null);
      setPlatforms(results[2].status === "fulfilled" ? results[2].value : null);
      setLoading(false);
    }

    fetchAll();
    return () => { cancelled = true; };
  }, [slug]);

  if (loading) {
    return (
      <p className="text-base text-muted-foreground font-mono py-8">
        Loading analytics...
      </p>
    );
  }

  const hasData = pricing || timing || platforms;
  if (!hasData) return null;

  return (
    <div className="space-y-6 mb-12">
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
        Market Intelligence
      </p>
      {pricing && <PricePositioningChart data={pricing} />}
      {timing && <ReleaseTimingChart data={timing} />}
      {platforms && <PlatformGapsChart data={platforms} />}
    </div>
  );
}
