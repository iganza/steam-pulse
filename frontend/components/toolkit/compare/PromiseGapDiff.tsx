"use client";

import { SectionLabel } from "@/components/game/SectionLabel";
import type { CompareGameData } from "@/lib/compare-types";

interface PromiseGapDiffProps {
  data: CompareGameData[];
}

const SECTIONS = [
  { key: "promises_delivered" as const, label: "Delivered", color: "var(--positive)" },
  { key: "promises_broken" as const, label: "Broken", color: "var(--negative)" },
  { key: "hidden_strengths" as const, label: "Hidden Strengths", color: "var(--gem)" },
];

const MATCH_COLORS: Record<string, string> = {
  aligned: "var(--positive)",
  partial_mismatch: "var(--gem)",
  significant_mismatch: "var(--negative)",
};

export function PromiseGapDiff({ data }: PromiseGapDiffProps) {
  return (
    <div className="rounded-xl bg-card border border-border p-6" data-testid="compare-promise-gap-diff">
      <SectionLabel>Promise Gap</SectionLabel>
      <div className="space-y-5">
        {SECTIONS.map((section) => (
          <div key={section.key}>
            <div
              className="text-xs uppercase tracking-wider font-mono mb-2"
              style={{ color: section.color }}
            >
              {section.label}
            </div>
            <div className="space-y-2">
              {data.map((d) => {
                const items = d.report?.store_page_alignment?.[section.key] ?? null;
                return (
                  <div
                    key={d.appid}
                    className="grid grid-cols-[160px_1fr] gap-4 text-sm border-t border-border/50 pt-2"
                  >
                    <div className="font-medium truncate">{d.meta.name}</div>
                    <div className="text-muted-foreground">
                      {items && items.length > 0 ? items.join(" · ") : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        <div>
          <div className="text-xs uppercase tracking-wider font-mono mb-2 text-muted-foreground">
            Audience Match
          </div>
          <div className="flex flex-wrap gap-3">
            {data.map((d) => {
              const match = d.report?.store_page_alignment?.audience_match;
              return (
                <div
                  key={d.appid}
                  className="flex items-center gap-2 text-xs rounded-full px-3 py-1 border border-border"
                >
                  <span className="font-medium">{d.meta.name}:</span>
                  <span style={{ color: match ? MATCH_COLORS[match] : undefined }}>
                    {match ?? "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
