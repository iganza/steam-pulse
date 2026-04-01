"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";

export function TrendStackedBarChart({
  data,
  series,
  granularity,
  height = 300,
}: {
  data: TrendPeriod[];
  series: { key: string; label: string; color: string }[];
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

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip
          contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          formatter={(value: unknown, name: unknown) => {
            const s = series.find((s) => s.key === String(name));
            return [Number(value).toLocaleString(), s?.label ?? String(name)];
          }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stackId="stack"
            fill={s.color}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
