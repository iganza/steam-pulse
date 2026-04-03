"use client";

import type { LensId, ToolkitFilters } from "@/lib/toolkit-state";
import { SentimentDrillLens } from "./lenses/SentimentDrillLens";
import { CompareLens } from "./lenses/CompareLens";
import { ExplorerLens } from "./lenses/ExplorerLens";
import { BenchmarkLens } from "./lenses/BenchmarkLens";
import { MarketMapLens } from "./lenses/MarketMapLens";
import { TrendsLens } from "./lenses/TrendsLens";

interface LensRendererProps {
  lens: LensId;
  filters: ToolkitFilters;
  isPro: boolean;
  override?: React.ReactNode;
}

export function LensRenderer({
  lens,
  filters,
  isPro,
  override,
}: LensRendererProps) {
  if (override) return <>{override}</>;

  const props = { filters, isPro };

  switch (lens) {
    case "sentiment":
      return <SentimentDrillLens {...props} />;
    case "compare":
      return <CompareLens {...props} />;
    case "explorer":
      return <ExplorerLens {...props} />;
    case "benchmark":
      return <BenchmarkLens {...props} />;
    case "market-map":
      return <MarketMapLens {...props} />;
    case "trends":
      return <TrendsLens {...props} />;
    default: {
      const _exhaustive: never = lens;
      return null;
    }
  }
}
