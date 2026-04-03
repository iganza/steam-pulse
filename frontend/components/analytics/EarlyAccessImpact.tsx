"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { EarlyAccessImpact as EarlyAccessImpactData, ReviewSegment } from "@/lib/types";

interface EarlyAccessImpactProps {
  data: EarlyAccessImpactData;
}

function pctColor(pct: number): string {
  if (pct >= 70) return "#22c55e";
  if (pct >= 50) return "#f59e0b";
  return "#ef4444";
}

function SegmentCard({ label, segment }: { label: string; segment: ReviewSegment }) {
  return (
    <div className="flex-1 rounded-lg p-4" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
      <p className="text-xs uppercase tracking-widest text-muted-foreground mb-2">{label}</p>
      <p className="text-sm text-muted-foreground">
        {segment.total.toLocaleString()} reviews
      </p>
      <p className="text-2xl font-mono font-bold mt-1" style={{ color: pctColor(segment.pct_positive) }}>
        {segment.pct_positive.toFixed(1)}%
      </p>
      <p className="text-xs text-muted-foreground mt-1">positive</p>
      <p className="text-sm font-mono mt-2">
        {segment.avg_playtime.toFixed(1)}h <span className="text-muted-foreground text-xs">avg playtime</span>
      </p>
    </div>
  );
}

export function EarlyAccessImpact({ data }: EarlyAccessImpactProps) {
  if (data.verdict === "no_ea" || !data.early_access || !data.post_launch) return null;

  const delta = data.impact_delta ?? 0;

  let arrowSymbol: string;
  let arrowColor: string;
  let deltaText: string;
  let badgeBg: string;
  let badgeLabel: string;

  if (data.verdict === "improved") {
    arrowSymbol = "\u2191";
    arrowColor = "#22c55e";
    deltaText = `+${delta.toFixed(1)}%`;
    badgeBg = "rgba(34,197,94,0.15)";
    badgeLabel = "Improved";
  } else if (data.verdict === "declined") {
    arrowSymbol = "\u2193";
    arrowColor = "#ef4444";
    deltaText = `${delta.toFixed(1)}%`;
    badgeBg = "rgba(239,68,68,0.15)";
    badgeLabel = "Declined";
  } else {
    arrowSymbol = "\u2014";
    arrowColor = "#6b7280";
    deltaText = "Stable";
    badgeBg = "rgba(107,114,128,0.15)";
    badgeLabel = "Stable";
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Early Access Impact</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-stretch gap-3">
          <SegmentCard label="Early Access" segment={data.early_access} />

          <div className="flex flex-col items-center justify-center px-2 min-w-[80px]">
            <span className="text-2xl" style={{ color: arrowColor }}>{arrowSymbol}</span>
            <span className="text-sm font-mono font-semibold mt-1" style={{ color: arrowColor }}>
              {deltaText}
            </span>
            <span
              className="mt-2 text-xs font-medium px-2 py-0.5 rounded-full"
              style={{ background: badgeBg, color: arrowColor }}
            >
              {badgeLabel}
            </span>
          </div>

          <SegmentCard label="Post-Launch" segment={data.post_launch} />
        </div>
      </CardContent>
    </Card>
  );
}
