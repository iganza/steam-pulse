"use client";

import { LineChart, Line, ResponsiveContainer } from "recharts";

interface MiniTrendLineProps {
  data: { period: string; value: number }[];
}

export function MiniTrendLine({ data }: MiniTrendLineProps) {
  if (data.length < 2) return null;

  return (
    <ResponsiveContainer width="100%" height={80}>
      <LineChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <Line
          type="monotone"
          dataKey="value"
          stroke="var(--teal)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
