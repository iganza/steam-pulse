"use client";

import { useRef } from "react";
import { X } from "lucide-react";
import type { MetricDefinition, MetricCategory, MetricUnit } from "@/lib/types";

const UNIT_BADGES: Record<MetricUnit, string> = {
  count: "#",
  pct: "%",
  currency: "$",
  score: "★",
};

const CATEGORY_LABELS: Record<MetricCategory, string> = {
  volume: "Volume",
  sentiment: "Sentiment",
  pricing: "Pricing",
  velocity: "Review Velocity",
  early_access: "Early Access",
  platform: "Platform",
};

const CATEGORY_ORDER: MetricCategory[] = [
  "volume",
  "sentiment",
  "pricing",
  "velocity",
  "early_access",
  "platform",
];

interface MetricPickerProps {
  catalog: MetricDefinition[];
  selected: string[];
  maxMetrics: number;
  onToggle: (metricId: string) => void;
  onClear: () => void;
}

export function MetricPicker({
  catalog,
  selected,
  maxMetrics,
  onToggle,
  onClear,
}: MetricPickerProps) {
  const byCategory = new Map<MetricCategory, MetricDefinition[]>();
  for (const m of catalog) {
    if (!byCategory.has(m.category)) byCategory.set(m.category, []);
    byCategory.get(m.category)!.push(m);
  }

  const atCap = selected.length >= maxMetrics;

  // Flat order across categories used for roving arrow-key navigation.
  // Build it in the same order as render (CATEGORY_ORDER) so Tab+Arrow match
  // visual left→right / top→bottom.
  const flatOrder: string[] = [];
  for (const cat of CATEGORY_ORDER) {
    const metrics = byCategory.get(cat);
    if (!metrics) continue;
    for (const m of metrics) flatOrder.push(m.id);
  }

  const chipRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusById(id: string | undefined) {
    if (!id) return;
    const el = chipRefs.current[id];
    if (el && !el.disabled) el.focus();
  }

  function onChipKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, id: string) {
    const idx = flatOrder.indexOf(id);
    if (idx === -1) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      // Find next non-disabled chip.
      for (let i = idx + 1; i < flatOrder.length; i++) {
        const el = chipRefs.current[flatOrder[i]];
        if (el && !el.disabled) { el.focus(); return; }
      }
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      for (let i = idx - 1; i >= 0; i--) {
        const el = chipRefs.current[flatOrder[i]];
        if (el && !el.disabled) { el.focus(); return; }
      }
    } else if (e.key === "Home") {
      e.preventDefault();
      focusById(flatOrder.find((fid) => !chipRefs.current[fid]?.disabled));
    } else if (e.key === "End") {
      e.preventDefault();
      focusById([...flatOrder].reverse().find((fid) => !chipRefs.current[fid]?.disabled));
    }
  }

  return (
    <div data-testid="builder-metric-picker" className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-muted-foreground">
          Metrics ({selected.length}/{maxMetrics})
        </span>
        {selected.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-muted-foreground hover:text-foreground"
            aria-label="Clear all metrics"
          >
            Clear
          </button>
        )}
      </div>

      {CATEGORY_ORDER.map((cat) => {
        const metrics = byCategory.get(cat);
        if (!metrics || metrics.length === 0) return null;
        return (
          <div key={cat} className="space-y-1.5">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
              {CATEGORY_LABELS[cat]}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {metrics.map((m) => {
                const isSelected = selected.includes(m.id);
                const disabled = !isSelected && atCap;
                return (
                  <button
                    key={m.id}
                    ref={(el) => { chipRefs.current[m.id] = el; }}
                    type="button"
                    disabled={disabled}
                    data-testid={`builder-metric-chip-${m.id}`}
                    data-selected={isSelected ? "true" : "false"}
                    onClick={() => onToggle(m.id)}
                    onKeyDown={(e) => onChipKeyDown(e, m.id)}
                    title={
                      disabled
                        ? `Free tier: 1 metric. Upgrade to Pro to combine up to ${maxMetrics}.`
                        : m.description
                    }
                    aria-pressed={isSelected}
                    className={`group flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-mono transition ${
                      isSelected
                        ? "border-[color:var(--teal)] bg-teal-500/10 text-foreground"
                        : "border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground"
                    } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    <span className="inline-flex items-center justify-center w-4 h-4 rounded text-[9px] bg-muted text-muted-foreground">
                      {UNIT_BADGES[m.unit]}
                    </span>
                    {m.label}
                    {isSelected && <X className="w-3 h-3 opacity-60 group-hover:opacity-100" />}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
