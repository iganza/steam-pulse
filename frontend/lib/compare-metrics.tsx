import type { CompareGameData, MetricRow } from "./compare-types";

function fmtNum(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString();
}

function fmtPrice(meta: CompareGameData["meta"]): string {
  if (meta.is_free) return "Free";
  if (meta.price_usd == null) return "—";
  return `$${meta.price_usd.toFixed(2)}`;
}

function relativeAge(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  const years = (Date.now() - d.getTime()) / (365.25 * 24 * 3600 * 1000);
  if (years < 0.08) return "just now";
  if (years < 1) return `${Math.round(years * 12)}mo ago`;
  return `${Math.round(years * 10) / 10}y ago`;
}

const TREND_ARROW: Record<string, string> = {
  improving: "↗",
  stable: "→",
  declining: "↘",
};

const TREND_VALUE: Record<string, number> = {
  improving: 1,
  stable: 0,
  declining: -1,
};

const COMMUNITY_ORDER: Record<string, number> = {
  thriving: 5,
  active: 4,
  declining: 2,
  dead: 0,
  not_applicable: 1,
};

const REFUND_RISK_ORDER: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

const CASUAL_ORDER: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

function depthPillScore(val: string | undefined): number {
  const map: Record<string, number> = {
    low: 1,
    short: 1,
    poor: 1,
    fair: 2,
    medium: 2,
    good: 3,
    high: 3,
    long: 3,
    excellent: 4,
    endless: 4,
  };
  return val ? map[val] ?? 0 : 0;
}

export const COMPARE_METRICS: MetricRow[] = [
  // ---------- Steam (free) ----------
  {
    id: "positive_pct",
    label: "Positive Reviews %",
    group: "steam",
    direction: "higher",
    free: true,
    render: ({ meta }) => {
      if (meta.positive_pct == null) return "—";
      return (
        <>
          <span>{Math.round(meta.positive_pct)}%</span>
          {meta.review_score_desc && (
            <span className="block text-xs text-muted-foreground">{meta.review_score_desc}</span>
          )}
        </>
      );
    },
    numeric: ({ meta }) => meta.positive_pct ?? null,
  },
  {
    id: "review_count",
    label: "Total Reviews",
    group: "steam",
    direction: "higher",
    free: true,
    render: ({ meta }) => fmtNum(meta.review_count),
    numeric: ({ meta }) => meta.review_count ?? null,
  },
  {
    id: "price_usd",
    label: "Price",
    group: "steam",
    direction: "lower",
    free: true,
    render: ({ meta }) => fmtPrice(meta),
    numeric: ({ meta }) => (meta.is_free ? 0 : meta.price_usd ?? null),
  },
  {
    id: "release_date",
    label: "Released",
    group: "steam",
    direction: "neutral",
    free: true,
    render: ({ meta }) => relativeAge(meta.release_date),
    numeric: ({ meta }) => (meta.release_date ? new Date(meta.release_date).getTime() : null),
  },

  // ---------- Intelligence ----------
  {
    id: "sentiment_trend",
    label: "Sentiment Trend",
    group: "intelligence",
    direction: "higher",
    free: true,
    render: ({ report }) => {
      const t = report?.sentiment_trend;
      if (!t) return "—";
      return `${TREND_ARROW[t] ?? ""} ${t}`;
    },
    numeric: ({ report }) =>
      report?.sentiment_trend ? TREND_VALUE[report.sentiment_trend] ?? null : null,
  },
  {
    id: "hidden_gem_score",
    label: "Hidden Gem Score",
    group: "intelligence",
    direction: "higher",
    free: false,
    render: ({ report }) => {
      const s = report?.hidden_gem_score;
      if (s == null) return "—";
      return `${Math.round(s * 100)}`;
    },
    numeric: ({ report }) => report?.hidden_gem_score ?? null,
  },
  {
    id: "promise_delivered_count",
    label: "Promises Delivered",
    group: "intelligence",
    direction: "higher",
    free: false,
    render: ({ report }) => fmtNum(report?.store_page_alignment?.promises_delivered.length ?? null),
    numeric: ({ report }) => report?.store_page_alignment?.promises_delivered.length ?? null,
  },
  {
    id: "promise_broken_count",
    label: "Promises Broken",
    group: "intelligence",
    direction: "lower",
    free: false,
    render: ({ report }) => fmtNum(report?.store_page_alignment?.promises_broken.length ?? null),
    numeric: ({ report }) => report?.store_page_alignment?.promises_broken.length ?? null,
  },
  {
    id: "hidden_strengths_count",
    label: "Hidden Strengths",
    group: "intelligence",
    direction: "higher",
    free: false,
    render: ({ report }) => fmtNum(report?.store_page_alignment?.hidden_strengths.length ?? null),
    numeric: ({ report }) => report?.store_page_alignment?.hidden_strengths.length ?? null,
  },
  {
    id: "content_depth",
    label: "Content Depth",
    group: "intelligence",
    direction: "higher",
    free: false,
    render: ({ report }) => {
      const cd = report?.content_depth;
      if (!cd) return "—";
      return `${cd.perceived_length} · ${cd.replayability} · ${cd.value_perception}`;
    },
    numeric: ({ report }) => {
      const cd = report?.content_depth;
      if (!cd) return null;
      return depthPillScore(cd.perceived_length) + depthPillScore(cd.replayability) + depthPillScore(cd.value_perception);
    },
  },
  {
    id: "community_health",
    label: "Community Health",
    group: "intelligence",
    direction: "higher",
    free: false,
    render: ({ report }) => report?.community_health?.overall ?? "—",
    numeric: ({ report }) =>
      report?.community_health?.overall ? COMMUNITY_ORDER[report.community_health.overall] ?? null : null,
  },

  // ---------- Risk ----------
  {
    id: "refund_risk",
    label: "Refund Risk",
    group: "risk",
    direction: "lower",
    free: false,
    render: ({ report }) => report?.refund_signals?.risk_level ?? "—",
    numeric: ({ report }) =>
      report?.refund_signals?.risk_level ? REFUND_RISK_ORDER[report.refund_signals.risk_level] ?? null : null,
  },
  {
    id: "churn_triggers_count",
    label: "Churn Triggers",
    group: "risk",
    direction: "lower",
    free: false,
    render: ({ report }) => fmtNum(report?.churn_triggers?.length ?? null),
    numeric: ({ report }) => report?.churn_triggers?.length ?? null,
  },
  {
    id: "technical_issues_count",
    label: "Technical Issues",
    group: "risk",
    direction: "lower",
    free: false,
    render: ({ report }) => fmtNum(report?.technical_issues?.length ?? null),
    numeric: ({ report }) => report?.technical_issues?.length ?? null,
  },

  // ---------- Audience ----------
  {
    id: "ideal_player",
    label: "Ideal Player",
    group: "audience",
    direction: "neutral",
    free: false,
    render: ({ report }) => report?.audience_profile?.ideal_player ?? "—",
    numeric: () => null,
  },
  {
    id: "casual_friendliness",
    label: "Casual Friendliness",
    group: "audience",
    direction: "higher",
    free: false,
    render: ({ report }) => report?.audience_profile?.casual_friendliness ?? "—",
    numeric: ({ report }) =>
      report?.audience_profile?.casual_friendliness
        ? CASUAL_ORDER[report.audience_profile.casual_friendliness] ?? null
        : null,
  },
  {
    id: "benchmark_percentile",
    label: "Genre Sentiment Rank",
    group: "audience",
    direction: "higher",
    free: false,
    render: ({ benchmarks }) => {
      if (!benchmarks || benchmarks.sentiment_rank == null) return "—";
      return `#${benchmarks.sentiment_rank} / ${benchmarks.cohort_size}`;
    },
    numeric: ({ benchmarks }) => {
      if (!benchmarks || benchmarks.sentiment_rank == null || benchmarks.cohort_size === 0) return null;
      // Lower rank = better; invert to percentile so higher is better.
      return 1 - benchmarks.sentiment_rank / benchmarks.cohort_size;
    },
  },
];

export const METRIC_GROUPS: { id: MetricRow["group"]; label: string }[] = [
  { id: "steam", label: "Steam" },
  { id: "intelligence", label: "Intelligence" },
  { id: "risk", label: "Risk" },
  { id: "audience", label: "Audience" },
];

/** Compute the set of leader column indices for a metric row. */
export function computeLeaders(
  metric: MetricRow,
  data: CompareGameData[],
): Set<number> {
  if (metric.direction === "neutral") return new Set();
  const values = data.map((d) => metric.numeric(d));
  const valid = values
    .map((v, i) => ({ v, i }))
    .filter((x): x is { v: number; i: number } => x.v != null);
  if (valid.length === 0) return new Set();
  const best =
    metric.direction === "higher"
      ? Math.max(...valid.map((x) => x.v))
      : Math.min(...valid.map((x) => x.v));
  return new Set(valid.filter((x) => x.v === best).map((x) => x.i));
}
