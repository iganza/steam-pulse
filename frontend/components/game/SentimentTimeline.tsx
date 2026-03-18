"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { TimelineEntry } from "@/lib/types";

interface SentimentTimelineProps {
  timeline: TimelineEntry[];
}

function formatWeek(weekStr: string): string {
  const d = new Date(weekStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function SentimentTimeline({ timeline }: SentimentTimelineProps) {
  if (timeline.length < 3) return null;

  return (
    <div data-testid="sentiment-timeline">
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
        Sentiment over time
      </p>
      <ResponsiveContainer width="100%" height={140}>
        <AreaChart
          data={timeline}
          margin={{ top: 4, right: 0, left: -20, bottom: 0 }}
        >
          <defs>
            <linearGradient id="tealGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="var(--teal)" stopOpacity={0.3} />
              <stop offset="95%" stopColor="var(--teal)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="week"
            tickFormatter={formatWeek}
            tick={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              fill: "var(--muted-foreground)",
            }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            ticks={[50, 100]}
            tick={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              fill: "var(--muted-foreground)",
            }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(value, _name, props) => [
              `${value}% positive (${(props as { payload: TimelineEntry }).payload.total} reviews)`,
              "Sentiment",
            ]}
            labelFormatter={(label) => `Week of ${formatWeek(String(label))}`}
            contentStyle={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
            }}
          />
          <Area
            type="monotone"
            dataKey="pct_positive"
            stroke="var(--teal)"
            strokeWidth={2}
            fill="url(#tealGrad)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SentimentTimelineSkeleton() {
  return (
    <div data-testid="sentiment-timeline-skeleton" className="animate-pulse">
      <div className="h-3 w-32 bg-secondary rounded mb-3" />
      <div className="h-[140px] bg-secondary rounded-lg" />
    </div>
  );
}
