"use client";

import type { BuilderChartType, MetricDefinition, MetricUnit } from "@/lib/types";

const CHART_LABELS: Record<BuilderChartType, string> = {
  bar: "Bar",
  line: "Line",
  stacked_area: "Stacked Area",
  composed: "Composed",
};

/**
 * Determine which chart types are compatible with the current metric
 * selection. Returns a map of type → disabledReason (null = allowed).
 */
export function chartTypeCompatibility(
  selected: MetricDefinition[],
): Record<BuilderChartType, string | null> {
  const count = selected.length;
  const units = new Set<MetricUnit>(selected.map((m) => m.unit));

  return {
    bar: null,
    line: null,
    stacked_area:
      count >= 2 && units.size === 1 && (units.has("count") || units.has("pct"))
        ? null
        : "Stacked area needs ≥2 metrics with the same unit (count or %).",
    composed: count >= 2 ? null : "Composed view needs ≥2 metrics.",
  };
}

interface ChartTypePickerProps {
  value: BuilderChartType;
  selected: MetricDefinition[];
  onChange: (t: BuilderChartType) => void;
}

export function ChartTypePicker({ value, selected, onChange }: ChartTypePickerProps) {
  const compat = chartTypeCompatibility(selected);
  const types: BuilderChartType[] = ["bar", "line", "stacked_area", "composed"];

  return (
    <div
      data-testid="builder-chart-type-picker"
      className="inline-flex rounded-lg border border-border overflow-hidden text-xs font-mono"
      role="radiogroup"
      aria-label="Chart type"
    >
      {types.map((t) => {
        const disabledReason = compat[t];
        const isActive = value === t;
        return (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={isActive}
            disabled={disabledReason !== null}
            data-testid={`builder-chart-type-${t}`}
            title={disabledReason ?? CHART_LABELS[t]}
            onClick={() => onChange(t)}
            className={`px-3 py-1 transition-colors ${
              isActive
                ? "bg-teal-500/20 text-teal-400"
                : "text-muted-foreground hover:text-foreground"
            } ${disabledReason ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
          >
            {CHART_LABELS[t]}
          </button>
        );
      })}
    </div>
  );
}
