"use client";

import { AreaChart, Area, ResponsiveContainer } from "recharts";
import type { TimelineEntry } from "@/lib/types";

interface MiniSentimentChartProps {
  timeline: TimelineEntry[];
}

export function MiniSentimentChart({ timeline }: MiniSentimentChartProps) {
  if (timeline.length < 2) return null;

  return (
    <ResponsiveContainer width="100%" height={80}>
      <AreaChart data={timeline} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="miniTealGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--teal)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="var(--teal)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="pct_positive"
          stroke="var(--teal)"
          strokeWidth={1.5}
          fill="url(#miniTealGrad)"
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
