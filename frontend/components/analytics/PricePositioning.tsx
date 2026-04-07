"use client";

import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { PricePositioning as PricePositioningData } from "@/lib/types";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface PricePositioningProps {
  data: PricePositioningData;
}

export function PricePositioning({ data }: PricePositioningProps) {
  if (data.distribution.length === 0) return null;

  const { summary } = data;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Price Positioning</CardTitle>
        <p className="text-xs text-muted-foreground">
          Price vs sentiment distribution for {data.genre}
        </p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart
            data={data.distribution}
            margin={{ top: 4, right: 0, left: -10, bottom: 0 }}
          >
            <XAxis
              dataKey="price_range"
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar yAxisId="left" dataKey="game_count" name="Games" radius={[4, 4, 0, 0]}>
              {data.distribution.map((item, idx) => (
                <Cell
                  key={idx}
                  fill={item.price_range === summary.sweet_spot ? "#f59e0b" : "#3b82f6"}
                />
              ))}
            </Bar>
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="avg_steam_pct"
              name="Avg Steam %"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3, fill: "#22c55e" }}
            />
          </ComposedChart>
        </ResponsiveContainer>

        <div className="mt-4 flex flex-wrap gap-3 text-xs">
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "rgba(245, 158, 11, 0.15)", border: "1px solid #f59e0b" }}
          >
            <span className="text-muted-foreground">Sweet Spot: </span>
            <span className="font-medium" style={{ color: "#f59e0b" }}>
              {summary.sweet_spot ?? "\u2014"}
            </span>
          </div>
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Avg Price: </span>
            <span className="font-medium">{summary.avg_price != null ? `$${summary.avg_price.toFixed(2)}` : "\u2014"}</span>
            <span className="text-muted-foreground"> &middot; Median: </span>
            <span className="font-medium">{summary.median_price != null ? `$${summary.median_price.toFixed(2)}` : "\u2014"}</span>
          </div>
          <div
            className="rounded-lg px-3 py-2"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="font-medium">{summary.free_count}</span>
            <span className="text-muted-foreground"> free, </span>
            <span className="font-medium">{summary.paid_count}</span>
            <span className="text-muted-foreground"> paid</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
