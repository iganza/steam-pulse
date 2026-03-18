"use client";

import Link from "next/link";
import type { PlaytimeBucket } from "@/lib/types";

interface PlaytimeChartProps {
  buckets: PlaytimeBucket[];
  insight: string;
  isPro?: boolean;
}

function barColor(pct: number): string {
  if (pct >= 80) return "#22c55e";
  if (pct >= 60) return "#f59e0b";
  return "#ef4444";
}

export function PlaytimeChart({ buckets, insight, isPro = false }: PlaytimeChartProps) {
  const total = buckets.reduce((sum, b) => sum + b.reviews, 0);
  if (total < 50) return null;

  const maxPct = Math.max(...buckets.map((b) => b.pct_positive));

  return (
    <div data-testid="playtime-chart">
      <div className="flex items-center gap-2 mb-4">
        <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground">
          Sentiment by time invested
        </p>
        <div className="relative group cursor-help">
          <span className="text-[10px] font-mono text-muted-foreground border border-border rounded-full w-4 h-4 inline-flex items-center justify-center flex-shrink-0">
            ?
          </span>
          <div
            className="absolute left-6 top-0 hidden group-hover:block w-52 p-2 rounded-lg text-[10px] text-muted-foreground z-10"
            style={{ background: "var(--popover)", border: "1px solid var(--border)" }}
          >
            Players who've spent more time generally rate the game differently —
            revealing whether it's a first-impression hit or slow burn.
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {buckets.map((b) => {
          const color = barColor(b.pct_positive);
          const isHighest = b.pct_positive === maxPct;
          return (
            <div
              key={b.bucket}
              data-bucket={b.bucket}
              data-pct={b.pct_positive}
              className={`flex items-center gap-3 px-2 py-1.5 rounded-lg ${isHighest ? "ring-1 ring-inset" : ""}`}
              style={isHighest ? { background: `${color}10` } : undefined}
            >
              <span className="text-[10px] font-mono text-muted-foreground w-14 flex-shrink-0">
                {b.bucket}
              </span>
              <div className="flex-1 h-2 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${b.pct_positive}%`, background: color }}
                />
              </div>
              <span
                className="text-xs font-mono font-medium w-8 text-right flex-shrink-0"
                style={{ color }}
              >
                {b.pct_positive}%
              </span>
              <span className="text-[10px] font-mono text-muted-foreground w-16 text-right flex-shrink-0">
                {b.reviews.toLocaleString()} rev
              </span>
            </div>
          );
        })}
      </div>

      {insight && (
        <div className="mt-4 relative">
          <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
            <p className="text-xs text-muted-foreground leading-relaxed italic">
              {insight}
            </p>
          </div>
          {!isPro && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Link
                href="/pro"
                className="text-xs font-mono px-3 py-1 rounded-full"
                style={{
                  background: "rgba(45,185,212,0.15)",
                  color: "var(--teal)",
                  border: "1px solid rgba(45,185,212,0.3)",
                }}
              >
                Pro insight →
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function PlaytimeChartSkeleton() {
  return (
    <div data-testid="playtime-chart-skeleton" className="animate-pulse space-y-3">
      <div className="h-3 w-40 bg-secondary rounded mb-4" />
      {[...Array(5)].map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="w-14 h-2 bg-secondary rounded" />
          <div className="flex-1 h-2 bg-secondary rounded-full" />
          <div className="w-8 h-2 bg-secondary rounded" />
          <div className="w-16 h-2 bg-secondary rounded" />
        </div>
      ))}
    </div>
  );
}

export function computePlaytimeInsight(buckets: PlaytimeBucket[]): string {
  const early = buckets.find((b) => b.bucket === "<2h" || b.bucket === "2-10h");
  const deep = buckets.find((b) => b.bucket === "50-200h" || b.bucket === "200h+");
  if (!early || !deep) return "";
  const delta = deep.pct_positive - early.pct_positive;
  if (delta >= 15) {
    return `Players who invest more time rate this game significantly higher (+${delta}pts) — a strong signal of a slow-burn experience that rewards patience.`;
  }
  if (delta <= -15) {
    return `Early players rate this game higher than veterans (-${Math.abs(delta)}pts) — suggesting the game has strong first impressions but may not hold up over time.`;
  }
  return `Sentiment is consistent across all playtime ranges — players feel the same way whether they've played 2 hours or 200.`;
}
