"use client";

import { TrendBarChart } from "@/components/trends/TrendBarChart";
import { TrendStackedArea } from "@/components/trends/TrendStackedArea";
import { TrendComposed } from "@/components/trends/TrendComposed";
import type {
  BuilderChartType,
  Granularity,
  MetricDefinition,
  TrendPeriod,
  TrendQueryPeriod,
} from "@/lib/types";
import { colorForIndex } from "./palette";

interface ChartResolverProps {
  selected: MetricDefinition[];
  chartType: BuilderChartType;
  data: TrendQueryPeriod[];
  granularity: Granularity;
  normalize: boolean;
}

/**
 * Route a (metrics, chartType, data) tuple to the right chart primitive.
 *
 * Compatibility & auto-routing rules (matching UX principles):
 *  - Bar / line: always allowed.
 *  - Stacked area: requires ≥2 metrics with the same unit ∈ {count, pct}.
 *  - Composed: requires ≥2 metrics.
 *  - Mixed-unit ≥2 metrics: always routes to composed with bars (counts) on
 *    the left axis and lines (currency/pct/score) on the right axis. This
 *    is the only legitimate dual-axis case.
 *
 * If the caller's chartType is incompatible with the current selection, this
 * component silently renders a compatible type via `effectiveChartType()`.
 * The parent lens watches the same helper to surface a "Switched to X" note
 * — see `BuilderLens.tsx` fallback note.
 */
export function ChartResolver({
  selected,
  chartType,
  data,
  granularity,
  normalize,
}: ChartResolverProps) {
  if (selected.length === 0 || data.length === 0) {
    return (
      <div
        data-testid="builder-chart-empty"
        className="flex items-center justify-center text-muted-foreground text-sm h-[300px]"
      >
        No data to display.
      </div>
    );
  }

  const rows = data as unknown as TrendPeriod[];
  const effective = effectiveChartType(selected, chartType);
  const units = new Set(selected.map((m) => m.unit));
  const mixedUnits = units.size > 1;

  // Mixed-unit multi-metric → dual-axis composed. Group metrics by unit;
  // the first unit goes on the left axis (as bars when it is `count`, else
  // as lines), the remaining units go on the right axis as lines. This
  // keeps e.g. `avg_paid_price` (currency) and `avg_steam_pct` (pct) on
  // separate axes instead of squashing them onto one scale.
  if (mixedUnits && selected.length >= 2) {
    const byUnit = new Map<string, MetricDefinition[]>();
    for (const m of selected) {
      const bucket = byUnit.get(m.unit) ?? [];
      bucket.push(m);
      byUnit.set(m.unit, bucket);
    }
    const units = Array.from(byUnit.keys());
    // Prefer `count` on the left axis (bars) when present, otherwise the
    // first declared unit — keeps counts as bars wherever possible.
    const leftUnit = units.includes("count") ? "count" : units[0];
    const leftMetrics = byUnit.get(leftUnit) ?? [];
    const rightMetrics = units
      .filter((u) => u !== leftUnit)
      .flatMap((u) => byUnit.get(u) ?? []);

    const bars =
      leftUnit === "count"
        ? leftMetrics.map((m, i) => ({
            dataKey: m.id,
            label: m.label,
            color: colorForIndex(i),
          }))
        : [];
    // When the left unit isn't `count`, render its metrics as left-axis
    // lines. Right-axis lines get explicit `axis: "right"` so TrendComposed
    // forces the dual axis on even if there are no bars.
    const leftLines =
      leftUnit === "count"
        ? []
        : leftMetrics.map((m, i) => ({
            dataKey: m.id,
            label: m.label,
            color: colorForIndex(i),
            axis: "left" as const,
          }));
    const rightLines = rightMetrics.map((m, i) => ({
      dataKey: m.id,
      label: m.label,
      color: colorForIndex(i + leftMetrics.length),
      axis: "right" as const,
    }));

    return (
      <TrendComposed
        data={rows}
        bars={bars}
        lines={[...leftLines, ...rightLines]}
        granularity={granularity}
        height={360}
      />
    );
  }

  switch (effective) {
    case "bar": {
      if (selected.length === 1) {
        const m = selected[0];
        return (
          <TrendBarChart
            data={rows}
            dataKey={m.id}
            granularity={granularity}
            color={colorForIndex(0)}
            height={360}
          />
        );
      }
      // Multi-metric "bar" without mixed units → grouped bars via composed.
      return (
        <TrendComposed
          data={rows}
          bars={selected.map((m, i) => ({
            dataKey: m.id,
            label: m.label,
            color: colorForIndex(i),
          }))}
          lines={[]}
          granularity={granularity}
          height={360}
        />
      );
    }
    case "line": {
      // Line mode routes through composed with no bars.
      return (
        <TrendComposed
          data={rows}
          bars={[]}
          lines={selected.map((m, i) => ({
            dataKey: m.id,
            label: m.label,
            color: colorForIndex(i),
          }))}
          granularity={granularity}
          height={360}
        />
      );
    }
    case "stacked_area": {
      return (
        <TrendStackedArea
          data={rows}
          series={selected.map((m, i) => ({
            key: m.id,
            label: m.label,
            color: colorForIndex(i),
          }))}
          granularity={granularity}
          normalized={normalize}
          height={360}
        />
      );
    }
    case "composed": {
      // Heuristic: counts as bars, everything else as lines.
      const bars = selected
        .filter((m) => m.unit === "count")
        .map((m, i) => ({ dataKey: m.id, label: m.label, color: colorForIndex(i) }));
      const lines = selected
        .filter((m) => m.unit !== "count")
        .map((m, i) => ({
          dataKey: m.id,
          label: m.label,
          color: colorForIndex(i + bars.length),
        }));
      return (
        <TrendComposed
          data={rows}
          bars={bars}
          lines={lines}
          granularity={granularity}
          height={360}
        />
      );
    }
  }
}

/**
 * If the requested chart type is incompatible with the current selection,
 * fall back to the most reasonable compatible type.
 *
 * Rules (mirror the render-time routing in <ChartResolver/>):
 *  - Mixed-unit multi-metric → always `composed` (dual-axis).
 *  - `stacked_area` requires ≥2 metrics of the same unit ∈ {count, pct}.
 *  - `composed` requires ≥2 metrics.
 *  - Otherwise the requested type is honored.
 */
export function effectiveChartType(
  selected: MetricDefinition[],
  requested: BuilderChartType,
): BuilderChartType {
  const units = new Set(selected.map((m) => m.unit));
  const count = selected.length;

  // Mixed-unit multi-metric is always rendered as dual-axis composed — so
  // encode that in the effective type. Without this, the fallback note and
  // the chart-type UI can disagree with what the chart resolver actually
  // draws.
  if (count >= 2 && units.size > 1) {
    return "composed";
  }

  if (requested === "stacked_area") {
    const sameUnit = units.size === 1;
    const stackable = units.has("count") || units.has("pct");
    if (count < 2 || !sameUnit || !stackable) {
      return count >= 2 ? "composed" : "bar";
    }
  }
  if (requested === "composed" && count < 2) {
    return "bar";
  }
  return requested;
}
