"use client";

import { useRef } from "react";
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
  const btnRefs = useRef<Record<BuilderChartType, HTMLButtonElement | null>>({
    bar: null,
    line: null,
    stacked_area: null,
    composed: null,
  });

  function focusType(t: BuilderChartType | undefined) {
    if (!t) return;
    const el = btnRefs.current[t];
    if (el && !el.disabled) el.focus();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, t: BuilderChartType) {
    const idx = types.indexOf(t);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      for (let i = idx + 1; i < types.length; i++) {
        const next = types[i];
        if (!compat[next]) { focusType(next); onChange(next); return; }
      }
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      for (let i = idx - 1; i >= 0; i--) {
        const prev = types[i];
        if (!compat[prev]) { focusType(prev); onChange(prev); return; }
      }
    } else if (e.key === "Home") {
      e.preventDefault();
      const first = types.find((x) => !compat[x]);
      if (first) { focusType(first); onChange(first); }
    } else if (e.key === "End") {
      e.preventDefault();
      const last = [...types].reverse().find((x) => !compat[x]);
      if (last) { focusType(last); onChange(last); }
    } else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (!compat[t]) onChange(t);
    }
  }

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
            ref={(el) => { btnRefs.current[t] = el; }}
            type="button"
            role="radio"
            aria-checked={isActive}
            // Roving tabindex: only the active option is in the tab order.
            tabIndex={isActive ? 0 : -1}
            disabled={disabledReason !== null}
            data-testid={`builder-chart-type-${t}`}
            title={disabledReason ?? CHART_LABELS[t]}
            onClick={() => onChange(t)}
            onKeyDown={(e) => onKeyDown(e, t)}
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
