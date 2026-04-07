import type { LensId } from "./toolkit-state";

export interface LensDefinition {
  id: LensId;
  label: string;
  icon: string;
  pro: boolean;
  description: string;
}

export const LENS_REGISTRY: LensDefinition[] = [
  {
    id: "sentiment",
    label: "Sentiment Drill",
    icon: "BarChart3",
    pro: false,
    description: "Deep sentiment analysis for a single game",
  },
  {
    id: "compare",
    label: "Compare",
    icon: "Swords",
    // Free users can compare exactly 2 games with a limited metric set.
    // The lens itself gates pro metrics internally via MetricsGrid's blur overlay.
    pro: false,
    description: "Side-by-side comparison of multiple games",
  },
  {
    id: "explorer",
    label: "Explorer",
    icon: "Table",
    pro: true,
    description: "Sortable table with every computed metric as a column",
  },
  {
    id: "benchmark",
    label: "Benchmark",
    icon: "Target",
    pro: true,
    description: "Percentile rankings within genre or tag",
  },
  {
    id: "market-map",
    label: "Market Map",
    icon: "PieChart",
    pro: true,
    description: "Aggregate distributions across the filtered catalog",
  },
  {
    id: "trends",
    label: "Trends",
    icon: "TrendingUp",
    pro: true,
    description: "Time-series trends for any metric",
  },
  {
    id: "builder",
    label: "Chart Builder",
    icon: "Hammer",
    // Free tier has a 1-metric cap; richer capabilities are gated inside the lens.
    pro: false,
    description: "Compose your own chart from any metric",
  },
];

export function getLens(id: LensId): LensDefinition {
  const lens = LENS_REGISTRY.find((l) => l.id === id);
  if (!lens) throw new Error(`Unknown lens: ${id}`);
  return lens;
}
