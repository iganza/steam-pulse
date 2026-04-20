"use client";

import type { Benchmarks } from "@/lib/types";

interface CompetitiveBenchmarkProps {
  benchmarks: Benchmarks;
  genre?: string;
  year?: number;
}

function percentileLabel(rank: number): string {
  const pct = Math.round(rank * 100);
  if (pct >= 50) return `Top ${100 - pct}%`;
  return `Bottom ${pct}%`;
}

function BenchmarkBar({ label, rank, value }: { label: string; rank: number; value: string }) {
  const fillPct = Math.round(rank * 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
          {label}
        </span>
        <span
          className="text-sm font-mono font-medium"
          style={{ color: "var(--teal)" }}
        >
          {value}
        </span>
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden relative"
        style={{ background: "var(--border)" }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${fillPct}%`, background: "var(--teal)" }}
        />
      </div>
    </div>
  );
}

export function CompetitiveBenchmark({
  benchmarks,
  genre,
  year,
}: CompetitiveBenchmarkProps) {
  if (benchmarks.cohort_size < 10) return null;

  return (
    <div data-testid="competitive-benchmark">
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Compared to {benchmarks.cohort_size.toLocaleString()} similar games
          {genre ? ` in the ${genre} genre` : ""}
          {year ? ` released in ${year}` : ""}.
        </p>
        {benchmarks.sentiment_rank !== null && (
          <BenchmarkBar
            label="Sentiment vs. similar games"
            rank={benchmarks.sentiment_rank}
            value={percentileLabel(benchmarks.sentiment_rank)}
          />
        )}
        {benchmarks.popularity_rank !== null && (
          <BenchmarkBar
            label="Popularity vs. similar games"
            rank={benchmarks.popularity_rank}
            value={percentileLabel(benchmarks.popularity_rank)}
          />
        )}
      </div>
    </div>
  );
}
