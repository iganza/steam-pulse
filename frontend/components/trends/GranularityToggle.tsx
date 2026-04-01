"use client";

import type { Granularity } from "@/lib/types";

const OPTIONS: { value: Granularity; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

export function GranularityToggle({
  value,
  onChange,
  disabled,
}: {
  value: Granularity;
  onChange: (g: Granularity) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex rounded-lg border border-border overflow-hidden">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          disabled={disabled}
          className={`px-3 py-1.5 text-xs font-mono uppercase tracking-widest transition-colors ${
            value === opt.value
              ? "bg-teal-500/20 text-teal-400"
              : "text-muted-foreground hover:text-foreground"
          } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
