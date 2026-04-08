"use client";

import type { LensId, ToolkitFilters } from "@/lib/toolkit-state";
import { SentimentDrillLens } from "./lenses/SentimentDrillLens";
import { CompareLens } from "./lenses/CompareLens";
import { TrendsLens } from "./lenses/TrendsLens";
import { BuilderLens } from "./lenses/BuilderLens";

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
    case "trends":
      return <TrendsLens {...props} />;
    case "builder":
      return <BuilderLens {...props} />;
    default: {
      const _exhaustive: never = lens;
      return null;
    }
  }
}
