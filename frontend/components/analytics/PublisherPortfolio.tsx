"use client";

import Link from "next/link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { PublisherPortfolio as PublisherPortfolioData, PublisherGame } from "@/lib/types";

/** Parse YYYY-MM-DD as a local date (avoids UTC timezone shift). */
function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatShortDate(dateStr: string): string {
  return parseLocalDate(dateStr).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

interface PublisherPortfolioProps {
  data: PublisherPortfolioData;
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function sentimentColor(pct: number): string {
  if (pct >= 70) return "#22c55e";
  if (pct >= 50) return "#f59e0b";
  return "#ef4444";
}

function trajectoryLabel(t: string): string {
  switch (t) {
    case "improving":
      return "Improving";
    case "declining":
      return "Declining";
    case "stable":
      return "Stable";
    case "single_title":
      return "Single Title";
    case "no_games":
      return "No Games";
    default:
      return t;
  }
}

function trajectoryColor(t: string): string {
  switch (t) {
    case "improving":
      return "#22c55e";
    case "declining":
      return "#ef4444";
    case "stable":
      return "#f59e0b";
    default:
      return "var(--muted-foreground)";
  }
}

export function PublisherPortfolio({ data }: PublisherPortfolioProps) {
  if (data.games.length === 0) return null;

  const { summary } = data;

  const sortedGames = [...data.games].sort((a, b) => {
    if (!a.release_date) return 1;
    if (!b.release_date) return -1;
    return parseLocalDate(b.release_date).getTime() - parseLocalDate(a.release_date).getTime();
  });

  const trajectoryGames = data.games
    .filter((g): g is PublisherGame & { release_date: string } => g.release_date != null && g.positive_pct != null)
    .sort((a, b) => parseLocalDate(a.release_date).getTime() - parseLocalDate(b.release_date).getTime())
    .map((g) => ({
      name: g.name,
      date: formatShortDate(g.release_date),
      positive_pct: g.positive_pct,
    }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{data.publisher}</CardTitle>
        <p className="text-xs text-muted-foreground">Publisher portfolio overview</p>
      </CardHeader>
      <CardContent>
        {/* Summary stat cards */}
        <div className="flex flex-wrap gap-3 mb-6">
          <div
            className="rounded-lg px-3 py-2 text-xs"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Total Games: </span>
            <span className="font-medium">{summary.total_games}</span>
          </div>
          <div
            className="rounded-lg px-3 py-2 text-xs"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Total Reviews: </span>
            <span className="font-medium">{formatCompact(summary.total_reviews)}</span>
          </div>
          <div
            className="rounded-lg px-3 py-2 text-xs"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">👍 Avg Steam: </span>
            <span className="font-medium" style={{ color: sentimentColor(summary.avg_steam_pct) }}>
              {summary.avg_steam_pct}%
            </span>
          </div>
          <div
            className="rounded-lg px-3 py-2 text-xs"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <span className="text-muted-foreground">Trajectory: </span>
            <span
              className="font-medium"
              style={{ color: trajectoryColor(summary.sentiment_trajectory) }}
            >
              {trajectoryLabel(summary.sentiment_trajectory)}
            </span>
          </div>
        </div>

        {/* Game grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
          {sortedGames.map((game) => (
            <GameCard key={game.appid} game={game} />
          ))}
        </div>

        {/* Sentiment trajectory chart */}
        {trajectoryGames.length >= 3 && (
          <div>
            <p className="text-eyebrow mb-3">
              Sentiment trajectory
            </p>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart
                data={trajectoryGames}
                margin={{ top: 4, right: 10, left: -10, bottom: 0 }}
              >
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => [`${value}%`, "Positive"]}
                  labelFormatter={(_label, payload) => {
                    if (payload && payload.length > 0) {
                      return (payload[0].payload as { name: string }).name;
                    }
                    return "";
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="positive_pct"
                  stroke="var(--teal)"
                  strokeWidth={2}
                  dot={{ r: 4, fill: "var(--teal)" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GameCard({ game }: { game: PublisherGame }) {
  const priceLabel = game.is_free ? "Free" : game.price_usd != null ? `$${game.price_usd.toFixed(2)}` : "N/A";

  return (
    <div
      className="rounded-lg overflow-hidden text-xs"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      {game.header_image && (
        <img
          src={game.header_image}
          alt={game.name}
          className="w-full h-20 object-cover"
        />
      )}
      <div className="p-2 flex flex-col gap-1">
        <Link
          href={`/games/${game.appid}/${game.slug}`}
          className="font-medium hover:underline truncate"
        >
          {game.name}
        </Link>
        <div className="flex items-center gap-2 text-muted-foreground">
          {game.release_date && (
            <span>{formatShortDate(game.release_date)}</span>
          )}
          <span>{priceLabel}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">
            {formatCompact(game.review_count ?? 0)} reviews
          </span>
          {game.positive_pct != null && (
            <div className="flex-1 flex items-center gap-1">
              <div
                className="h-2 flex-1 rounded-full overflow-hidden"
                style={{ background: "var(--border)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${game.positive_pct}%`,
                    background: sentimentColor(game.positive_pct),
                  }}
                />
              </div>
              <span className="font-mono" style={{ color: sentimentColor(game.positive_pct) }}>
                {game.positive_pct}%
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
