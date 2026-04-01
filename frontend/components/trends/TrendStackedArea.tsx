"use client";

import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ComposedChart, Line, Legend,
} from "recharts";
import type { Granularity, TrendPeriod } from "@/lib/types";
import { formatPeriodLabel } from "./periodLabel";

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

  // For normalized view, pre-compute 0–100 percentages so the chart receives
  // explicit values. We do NOT use stackOffset="expand" — combining that with
  // pre-computed percentages causes Recharts to re-normalize to 0–1 internally,
  // which makes the tooltip formatter receive fractional values and display
  // "0.3%" instead of "30%".
  // Raw counts are preserved as "_raw_<key>" so the tooltip can show both.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartData: any[] = normalized
    ? data.map((d) => {
        const rec = d as unknown as Record<string, number>;
        const total = series.reduce((sum, s) => sum + (rec[s.key] || 0), 0);
        const row: Record<string, unknown> = { period: d.period };
        for (const s of series) {
          row[s.key] = total > 0 ? Math.round((rec[s.key] || 0) / total * 1000) / 10 : 0;
          row[`_raw_${s.key}`] = rec[s.key] || 0;
        }
        if (secondaryLine) {
          row[secondaryLine.dataKey] = (rec as Record<string, unknown>)[secondaryLine.dataKey];
        }
        return row;
      })
    : data;

  const tooltipStyle = { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tooltipFormatter = (value: unknown, name: unknown, props: any): any => {
    const n = String(name);
    // Recharts passes the `name` prop (label) not `dataKey`, so match by both.
    if (value == null) {
      if (secondaryLine && (n === secondaryLine.dataKey || n === secondaryLine.label)) return ["N/A", secondaryLine.label];
      const s = series.find((s) => s.key === n || s.label === n);
      return ["N/A", s?.label ?? n];
    }
    const v = Number(value);
    if (secondaryLine && (n === secondaryLine.dataKey || n === secondaryLine.label)) {
      return [v.toFixed(2), secondaryLine.label];
    }
    const s = series.find((s) => s.key === n || s.label === n);
    if (normalized && s) {
      const rawCount = props?.payload?.[`_raw_${s.key}`];
      const rawStr = rawCount != null ? ` (${Number(rawCount).toLocaleString()})` : "";
      return [`${v.toFixed(1)}%${rawStr}`, s.label];
    }
    return [normalized ? `${v.toFixed(1)}%` : v.toLocaleString(), s?.label ?? n];
  };

  // Y-axis formatter: values are already 0–100 when normalized.
  const yTickFormatter = normalized ? (v: number) => `${v.toFixed(0)}%` : undefined;
  const tickFmt = (v: string) => formatPeriodLabel(v, granularity);

  if (secondaryLine) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} tickFormatter={tickFmt} />
          <YAxis yAxisId="left" tick={{ fontSize: 11 }} tickFormatter={yTickFormatter} />
          <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s) => (
            <Area
              key={s.key}
              yAxisId="left"
              type="monotone"
              dataKey={s.key}
              name={s.label}
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
            name={secondaryLine.label}
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
      <AreaChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="period" tick={{ fontSize: 11 }} tickFormatter={tickFmt} />
        <YAxis tick={{ fontSize: 11 }} tickFormatter={yTickFormatter} />
        <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {series.map((s) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
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
