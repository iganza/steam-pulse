import {
  parseAsArrayOf,
  parseAsBoolean,
  parseAsInteger,
  parseAsString,
  parseAsStringLiteral,
  useQueryStates,
} from "nuqs";

export const LENS_IDS = [
  "sentiment",
  "compare",
  "explorer",
  "benchmark",
  "market-map",
  "trends",
] as const;

export type LensId = (typeof LENS_IDS)[number];

const SENTIMENT_VALUES = ["positive", "mixed", "negative"] as const;
const PRICE_TIER_VALUES = ["free", "under_10", "10_to_20", "over_20"] as const;

export const DEFAULT_SORT = "review_count";

export const toolkitParsers = {
  lens: parseAsStringLiteral(LENS_IDS),
  genre: parseAsString.withDefault(""),
  tag: parseAsString.withDefault(""),
  q: parseAsString.withDefault(""),
  developer: parseAsString.withDefault(""),
  sentiment: parseAsStringLiteral(SENTIMENT_VALUES),
  price_tier: parseAsStringLiteral(PRICE_TIER_VALUES),
  min_reviews: parseAsInteger,
  year_from: parseAsInteger,
  year_to: parseAsInteger,
  deck: parseAsString.withDefault(""),
  has_analysis: parseAsBoolean,
  sort: parseAsString.withDefault(DEFAULT_SORT),
  appids: parseAsArrayOf(parseAsInteger, ",").withDefault([]),
};

export type ToolkitState = {
  [K in keyof typeof toolkitParsers]: ReturnType<
    (typeof toolkitParsers)[K]["parseServerSide"]
  >;
};

export type ToolkitFilters = Omit<ToolkitState, "lens">;

export interface LensProps {
  filters: ToolkitFilters;
  isPro: boolean;
}

export function useToolkitState() {
  return useQueryStates(toolkitParsers, { history: "push" });
}
