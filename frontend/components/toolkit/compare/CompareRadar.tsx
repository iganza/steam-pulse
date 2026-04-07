"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { SectionLabel } from "@/components/game/SectionLabel";
import type { CompareGameData } from "@/lib/compare-types";

interface CompareRadarProps {
  data: CompareGameData[];
}

const PALETTE = ["#2db9d4", "#c9973c", "#22c55e", "#a855f7"];

const AXES = [
  { key: "sentiment", label: "Sentiment" },
  { key: "reviewVolume", label: "Review Volume" },
  { key: "hiddenGem", label: "Hidden Gem" },
  { key: "contentDepth", label: "Content Depth" },
  { key: "communityHealth", label: "Community" },
  { key: "promiseAlignment", label: "Promise Match" },
] as const;

export function CompareRadar({ data }: CompareRadarProps) {
  const chartData = AXES.map((axis) => {
    const row: Record<string, string | number> = { axis: axis.label };
    data.forEach((d) => {
      row[d.meta.name] = d.radarAxes[axis.key];
    });
    return row;
  });

  return (
    <div className="rounded-xl bg-card border border-border p-6" data-testid="compare-radar">
      <SectionLabel>Shape Comparison</SectionLabel>
      <div style={{ height: 360 }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={chartData}>
            <PolarGrid stroke="rgba(255,255,255,0.08)" />
            <PolarAngleAxis dataKey="axis" tick={{ fill: "currentColor", fontSize: 12 }} />
            <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
            {data.map((d, i) => (
              <Radar
                key={d.appid}
                name={d.meta.name}
                dataKey={d.meta.name}
                stroke={PALETTE[i % PALETTE.length]}
                fill={PALETTE[i % PALETTE.length]}
                fillOpacity={0.15}
                strokeWidth={2}
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center gap-4 justify-center mt-3 flex-wrap">
        {data.map((d, i) => (
          <div key={d.appid} className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className="w-3 h-3 rounded-sm"
              style={{ background: PALETTE[i % PALETTE.length] }}
            />
            {d.meta.name}
          </div>
        ))}
      </div>
    </div>
  );
}
