"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { PlatformGaps as PlatformGapsData, PlatformStats } from "@/lib/types";

interface PlatformGapsProps {
  data: PlatformGapsData;
}

interface PlatformBarProps {
  label: string;
  stats: PlatformStats;
  totalGames: number;
  color: string;
}

function PlatformBar({ label, stats, totalGames, color }: PlatformBarProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          {stats.count}/{totalGames} games &middot; {stats.avg_sentiment != null ? `${stats.avg_sentiment}%` : "\u2014"} avg sentiment
        </span>
      </div>
      <div
        className="h-3 w-full rounded-full overflow-hidden"
        style={{ background: "var(--border)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${stats.pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

export function PlatformGaps({ data }: PlatformGapsProps) {
  if (data.total_games === 0) return null;

  const underservedPlatform = data.underserved;
  const underservedStats = underservedPlatform
    ? underservedPlatform === "linux"
      ? data.platforms.linux
      : underservedPlatform === "mac"
        ? data.platforms.mac
        : data.platforms.windows
    : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Platform Gaps</CardTitle>
        <p className="text-xs text-muted-foreground">
          Platform coverage across {data.total_games} {data.genre} games
        </p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          {data.platforms.windows && (
            <PlatformBar
              label="Windows"
              stats={data.platforms.windows}
              totalGames={data.total_games}
              color="#6b7280"
            />
          )}
          {data.platforms.mac && (
            <PlatformBar
              label="macOS"
              stats={data.platforms.mac}
              totalGames={data.total_games}
              color="#3b82f6"
            />
          )}
          {data.platforms.linux && (
            <PlatformBar
              label="Linux"
              stats={data.platforms.linux}
              totalGames={data.total_games}
              color="#f59e0b"
            />
          )}
        </div>

        {underservedPlatform && underservedStats && (
          <div
            className="mt-4 rounded-lg p-3 text-xs"
            style={{ background: "var(--card)", border: "1px solid var(--teal)" }}
          >
            <p>
              <span className="font-medium" style={{ color: "var(--teal)" }}>Opportunity: </span>
              Only {underservedStats.pct}% of {data.genre} games support{" "}
              {underservedPlatform === "mac" ? "macOS" : underservedPlatform === "linux" ? "Linux" : "Windows"}
              {" "}&mdash; those that do average {underservedStats.avg_sentiment != null ? `${underservedStats.avg_sentiment}%` : "\u2014"} positive
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
