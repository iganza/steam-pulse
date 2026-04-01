"use client";

import Link from "next/link";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { AudienceOverlap as AudienceOverlapData, AudienceOverlapEntry } from "@/lib/types";

interface AudienceOverlapProps {
  data: AudienceOverlapData;
  gameName: string;
  showAll?: boolean;
}

function sentimentColor(pct: number): string {
  if (pct >= 70) return "#22c55e";
  if (pct >= 50) return "#f59e0b";
  return "#ef4444";
}

export function AudienceOverlap({ data, gameName, showAll = false }: AudienceOverlapProps) {
  if (data.overlaps.length === 0) return null;

  const maxOverlap = Math.max(...data.overlaps.map((e) => e.overlap_pct)) || 1;
  const items: AudienceOverlapEntry[] = showAll
    ? data.overlaps
    : data.overlaps.slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audience Overlap</CardTitle>
        <p className="text-xs text-muted-foreground">
          Players who also reviewed {gameName} &middot; Based on {data.total_reviewers.toLocaleString()} unique reviewers
        </p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {items.map((entry) => (
            <div key={entry.appid} className="flex items-center gap-3">
              <img
                src={entry.header_image}
                alt={entry.name}
                width={60}
                height={28}
                className="rounded object-cover flex-shrink-0"
                style={{ width: 60, height: 28 }}
              />
              <div className="flex-1 min-w-0">
                <Link
                  href={`/games/${entry.appid}/${entry.slug}`}
                  className="text-sm font-medium hover:underline truncate block"
                >
                  {entry.name}
                </Link>
                <div className="mt-1 h-2 rounded-full overflow-hidden" style={{ background: "var(--border)" }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(entry.overlap_pct / maxOverlap) * 100}%`,
                      background: "var(--teal)",
                    }}
                  />
                </div>
              </div>
              <div className="text-right flex-shrink-0 text-xs whitespace-nowrap">
                <span className="font-mono font-medium">{entry.overlap_count.toLocaleString()}</span>
                <span className="text-muted-foreground"> shared ({entry.overlap_pct.toFixed(1)}%)</span>
                <span className="mx-1">&middot;</span>
                <span style={{ color: sentimentColor(entry.shared_sentiment_pct) }}>
                  {entry.shared_sentiment_pct.toFixed(0)}% agree
                </span>
              </div>
            </div>
          ))}
        </div>

        {!showAll && data.overlaps.length > 5 && (
          <div className="mt-4 text-center">
            <Link href="/pro" className="text-sm text-teal-400 hover:underline">
              See all overlaps &rarr;
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
