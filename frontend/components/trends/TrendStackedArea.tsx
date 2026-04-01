"use client";

import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ComposedChart, Line,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";

export function TrendStackedArea({
  data,
  series,
  granularity,
  normalized = true,
  secondaryLine,
  height = 300,
}: {
  data: TrendPeriod[];
  series: { key: string; label: string; color: string }[];
  granularity: Granularity;
  normalized?: boolean;
  secondaryLine?: { dataKey: string; label: string; color: string };
  height?: number;
}) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm" style={{ height }}>
        Not enough data for this view
      </div>
    );
  }

  // For normalized view, compute percentages per row
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartData: any[] = normalized
    ? data.map((d) => {
        const rec = d as unknown as Record<string, number>;
        const total = series.reduce((sum, s) => sum + (rec[s.key] || 0), 0);
        const row: Record<string, unknown> = { period: d.period };
        for (const s of series) {
          row[s.key] = total > 0 ? Math.round((rec[s.key] || 0) / total * 1000) / 10 : 0;
        }
        if (secondaryLine) {
          row[secondaryLine.dataKey] = (rec as Record<string, unknown>)[secondaryLine.dataKey];
        }
        return row;
      })
    : data;

  const tooltipStyle = { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tooltipFormatter = (value: unknown, name: unknown): any => {
    const v = Number(value);
    const n = String(name);
    if (secondaryLine && n === secondaryLine.dataKey) {
      return [v.toFixed(2), secondaryLine.label];
    }
    const s = series.find((s) => s.key === n);
    return [normalized ? `${v.toFixed(1)}%` : v.toLocaleString(), s?.label ?? n];
  };

  if (secondaryLine) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData} stackOffset={normalized ? "expand" : undefined}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 11 }}
            tickFormatter={normalized ? (v: number) => `${Math.round(v * 100)}%` : undefined}
          />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
          {series.map((s) => (
            <Area
              key={s.key}
              yAxisId="left"
              type="monotone"
              dataKey={s.key}
              stackId="1"
              fill={s.color}
              stroke={s.color}
              fillOpacity={0.6}
            />
          ))}
          <Line
            yAxisId="right"
            type="monotone"
            dataKey={secondaryLine.dataKey}
            stroke={secondaryLine.color}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} stackOffset={normalized ? "expand" : undefined}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} />
        <YAxis
          tick={{ fontSize: 11 }}
          tickFormatter={normalized ? (v: number) => `${Math.round(v * 100)}%` : undefined}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={tooltipFormatter}
        />
        {series.map((s) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stackId="1"
            fill={s.color}
            stroke={s.color}
            fillOpacity={0.6}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
