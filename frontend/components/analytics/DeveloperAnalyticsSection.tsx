"use client";

import { useState, useEffect } from "react";
import { getDeveloperAnalytics } from "@/lib/api";
import type { DeveloperPortfolio } from "@/lib/types";
import { DeveloperPortfolio as DeveloperPortfolioChart } from "@/components/analytics/DeveloperPortfolio";

interface DeveloperAnalyticsSectionProps {
  slug: string;
}

export function DeveloperAnalyticsSection({ slug }: DeveloperAnalyticsSectionProps) {
  const [portfolio, setPortfolio] = useState<DeveloperPortfolio | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const data = await getDeveloperAnalytics(slug);
        if (!cancelled) setPortfolio(data);
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

  if (!portfolio) return null;

  return (
    <div className="space-y-6 mb-8">
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
        Developer Analytics
      </p>
      <DeveloperPortfolioChart data={portfolio} />
    </div>
  );
}
