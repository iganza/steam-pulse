"use client";

import { Swords } from "lucide-react";
import { SectionLabel } from "@/components/game/SectionLabel";
import { COMPARE_METRICS, computeLeaders } from "@/lib/compare-metrics";
import type { CompareGameData } from "@/lib/compare-types";

interface WinsSummaryProps {
  data: CompareGameData[];
}

export function WinsSummary({ data }: WinsSummaryProps) {
  if (data.length < 2) return null;

  const scorable = COMPARE_METRICS.filter((m) => m.direction !== "neutral");
  const total = scorable.length;

  // wins[i] = array of metric labels where game i leads
  const wins: string[][] = data.map(() => []);
  // losses[i] = metric labels where game i is worst
  const losses: string[][] = data.map(() => []);

  for (const metric of scorable) {
    const leaders = computeLeaders(metric, data);
    leaders.forEach((i) => wins[i].push(metric.label));

    // Compute laggards (opposite extreme)
    const values = data.map((d) => metric.numeric(d));
    const valid = values
      .map((v, i) => ({ v, i }))
      .filter((x): x is { v: number; i: number } => x.v != null);
    if (valid.length === 0) continue;
    const worst =
      metric.direction === "higher"
        ? Math.min(...valid.map((x) => x.v))
        : Math.max(...valid.map((x) => x.v));
    valid
      .filter((x) => x.v === worst && !leaders.has(x.i))
      .forEach((x) => losses[x.i].push(metric.label));
  }

  return (
    <div className="rounded-xl bg-card border border-border p-6" data-testid="compare-wins-summary">
      <div className="flex items-center gap-2 mb-3">
        <Swords className="w-4 h-4" style={{ color: "var(--teal)" }} />
        <SectionLabel className="mb-0">Who Wins Where</SectionLabel>
      </div>
      <div className="space-y-4">
        {data.map((d, i) => {
          const wCount = wins[i].length;
          const top = wins[i].slice(0, 3).join(", ");
          const weak = losses[i].slice(0, 3).join(", ");
          return (
            <div key={d.appid} className="text-sm">
              <div className="font-semibold mb-1">
                {d.meta.name}{" "}
                <span
                  className="text-xs font-mono ml-1"
                  style={{ color: "var(--teal)" }}
                >
                  {wCount}/{total}
                </span>
              </div>
              <p className="text-muted-foreground leading-relaxed">
                {wCount > 0 ? (
                  <>
                    Strongest on <span className="text-foreground">{top}</span>.
                  </>
                ) : (
                  <>No clear wins across measured metrics.</>
                )}
                {weak && (
                  <>
                    {" "}
                    Losing ground on <span className="text-foreground">{weak}</span>.
                  </>
                )}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
