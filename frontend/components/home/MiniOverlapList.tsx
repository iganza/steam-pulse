"use client";

import type { AudienceOverlapEntry } from "@/lib/types";

interface MiniOverlapListProps {
  overlaps: AudienceOverlapEntry[];
}

export function MiniOverlapList({ overlaps }: MiniOverlapListProps) {
  const items = overlaps.slice(0, 3);
  if (items.length === 0) return null;

  const maxOverlap = Math.max(...items.map((e) => e.overlap_pct)) || 1;

  return (
    <div className="flex flex-col gap-2">
      {items.map((entry) => (
        <div key={entry.appid} className="flex items-center gap-2">
          <span className="text-xs truncate flex-1 text-muted-foreground">
            {entry.name}
          </span>
          <div
            className="h-1.5 rounded-full flex-shrink-0"
            style={{
              width: `${Math.max(20, (entry.overlap_pct / maxOverlap) * 60)}%`,
              background: "var(--teal)",
              opacity: 0.7,
            }}
          />
          <span className="text-xs font-mono text-muted-foreground flex-shrink-0">
            {entry.overlap_pct.toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}
