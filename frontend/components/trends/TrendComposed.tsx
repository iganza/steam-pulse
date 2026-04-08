"use client";

import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";
import { formatPeriodLabel } from "./periodLabel";

export function TrendComposed({
  data,
  bars,
  lines,
  granularity,
  height = 300,
}: {
  data: TrendPeriod[];
  bars: { dataKey: string; label: string; color: string }[];
  /** Per-line `axis` defaults to "left". Set to "right" to put a specific
   *  line on the right axis — useful for mixed-unit charts (e.g. currency
   *  + pct) where dumping all lines onto one axis would squash the smaller
   *  series. When any line explicitly asks for the right axis, the dual
   *  axis layout is forced on regardless of whether any bars are present.
   */
  lines: { dataKey: string; label: string; color: string; axis?: "left" | "right" }[];
  granularity: Granularity;
  height?: number;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm" style={{ height }}>
        Not enough data for this view
      </div>
    );
  }

  // Dual axis is needed when any line explicitly targets the right axis OR
  // when bars and lines coexist (bars always live on the left axis). When
  // only lines are present and none ask for the right axis, render a single
  // left axis to avoid an empty right axis.
  const anyLineOnRight = lines.some((l) => l.axis === "right");
  const hasDualAxis = anyLineOnRight || (bars.length > 0 && lines.length > 0);
  const defaultLineAxis: "left" | "right" =
    hasDualAxis && bars.length > 0 && !anyLineOnRight ? "right" : "left";

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} tickFormatter={(v) => formatPeriodLabel(v, granularity)} />
        <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
        {hasDualAxis && <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />}
        <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {bars.map((b) => (
          <Bar key={b.dataKey} yAxisId="left" dataKey={b.dataKey} name={b.label} fill={b.color} radius={[2, 2, 0, 0]} />
        ))}
        {lines.map((l) => (
          <Line
            key={l.dataKey}
            yAxisId={l.axis ?? defaultLineAxis}
            type="monotone"
            dataKey={l.dataKey}
            name={l.label}
            stroke={l.color}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
