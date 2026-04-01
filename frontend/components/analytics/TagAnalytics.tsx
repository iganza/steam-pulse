"use client";

import { useState, useEffect } from "react";
import { getTagTrend } from "@/lib/api";
import type { TagTrend } from "@/lib/types";
import { TagTrendChart } from "@/components/analytics/TagTrendChart";

interface TagAnalyticsProps {
  slug: string;
}

export function TagAnalytics({ slug }: TagAnalyticsProps) {
  const [trend, setTrend] = useState<TagTrend | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const data = await getTagTrend(slug);
        if (!cancelled) setTrend(data);
      } catch {
        // leave null on error
      }
      if (!cancelled) setLoading(false);
    }

    fetchData();
    return () => { cancelled = true; };
  }, [slug]);

  if (loading) {
    return (
      <p className="text-base text-muted-foreground font-mono py-8">
        Loading analytics...
      </p>
    );
  }

  if (!trend) return null;

  return (
    <div className="space-y-6 mb-10">
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
        Tag Trends
      </p>
      <TagTrendChart data={trend} />
    </div>
  );
}
