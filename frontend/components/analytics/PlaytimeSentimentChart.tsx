"use client";

import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { PlaytimeSentiment } from "@/lib/types";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface PlaytimeSentimentChartProps {
  data: PlaytimeSentiment;
}

export function PlaytimeSentimentChart({ data }: PlaytimeSentimentChartProps) {
  if (data.buckets.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Playtime vs Sentiment</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data.buckets}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="bucket"
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
              label={{ value: "Reviews", angle: -90, position: "insideLeft", fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
              label={{ value: "% Positive", angle: 90, position: "insideRight", fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar
              yAxisId="left"
              dataKey="total"
              name="Reviews"
              fill="#6b7280"
              radius={[2, 2, 0, 0]}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="pct_positive"
              name="% Positive"
              stroke="#22c55e"
              strokeWidth={2}
              dot={false}
            />
            {data.churn_point && (
              <ReferenceLine
                yAxisId="left"
                x={data.churn_point.bucket}
                stroke="#ef4444"
                strokeDasharray="5 5"
                label={{ value: `Churn Wall: ${data.churn_point.delta}% at ${data.churn_point.bucket}`, fill: "#ef4444", fontSize: 11, position: "top" }}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg p-3" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <p className="text-xs text-muted-foreground">Median Playtime</p>
            <p className="text-lg font-mono font-semibold">{data.median_playtime_hours}h</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <p className="text-xs text-muted-foreground">Value Score</p>
            <p className="text-lg font-mono font-semibold">
              {data.value_score !== null ? `${data.value_score} hrs/$` : "Free"}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
