import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getGames } from "@/lib/api";
import { GameCard } from "@/components/game/GameCard";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import type { Game } from "@/lib/types";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} \u2014 Developer Profile`,
    description: `All Steam games by ${name} \u2014 player sentiment analysis across their catalog.`,
    openGraph: {
      title: `${name} — Developer Profile — SteamPulse`,
      description: `All Steam games by ${name} — player sentiment analysis across their catalog.`,
      url: `https://steampulse.io/developer/${slug}`,
      images: [{ url: "/og-default.png", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${name} — Developer Profile — SteamPulse`,
      description: `All Steam games by ${name} — player sentiment analysis across their catalog.`,
    },
    alternates: { canonical: `https://steampulse.io/developer/${slug}` },
  };
}

function avg(games: Game[], key: keyof Game): number | null {
  const vals = games.map((g) => g[key]).filter((v): v is number => typeof v === "number");
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}

export default async function DeveloperPage({ params }: Props) {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  let games: Game[] = [];
  try {
    const result = await getGames({ developer: slug, sort: "review_count", limit: 100 });
    games = result.games ?? [];
  } catch {
    notFound();
  }

  const avgScore = avg(games, "sentiment_score") ?? avg(games, "positive_pct");
  const totalReviews = games.reduce((a, g) => a + (g.review_count ?? 0), 0);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Developers", href: "/search" },
            { label: name },
          ]}
        />

        <h1
          className="font-serif text-4xl font-bold mt-6 mb-6"
          style={{ letterSpacing: "-0.03em" }}
        >
          {name}
        </h1>

        {/* Cross-game stats */}
        <div className="grid grid-cols-3 gap-4 mb-10">
          {[
            { label: "Games", value: games.length },
            { label: "Total Reviews", value: totalReviews.toLocaleString() },
            { label: "Avg Sentiment", value: avgScore != null ? `${avgScore}` : "\u2014" },
          ].map((s) => (
            <div
              key={s.label}
              className="p-4 rounded-xl"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <p className="text-sm uppercase tracking-widest font-mono text-muted-foreground mb-1">
                {s.label}
              </p>
              <p className="font-mono text-lg font-bold">{s.value}</p>
            </div>
          ))}
        </div>

        {/* Sentiment across catalog */}
        {games.length > 0 && (
          <div className="mb-8 p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
            <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
              Sentiment Across Catalog
            </p>
            <div className="space-y-2">
              {games.slice(0, 8).map((game) => {
                const score = game.sentiment_score ?? game.positive_pct;
                const color =
                  (score ?? 0) >= 75 ? "#22c55e" : (score ?? 0) >= 50 ? "#f59e0b" : "#ef4444";
                return (
                  <div key={game.appid} className="flex items-center gap-3">
                    <Link
                      href={`/games/${game.appid}/${game.slug}`}
                      className="text-sm font-mono truncate w-40 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
                    >
                      {game.name}
                    </Link>
                    {score != null && (
                      <>
                        <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${score}%`, background: color }}
                          />
                        </div>
                        <span className="font-mono text-sm tabular-nums w-6 text-right" style={{ color }}>
                          {score}
                        </span>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Game list */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {games.map((game) => (
            <GameCard key={game.appid} game={game} />
          ))}
        </div>

        {games.length === 0 && (
          <p className="text-base text-muted-foreground text-center py-12">
            No games found for this developer.
          </p>
        )}

        {/* Pro CTA */}
        <p className="mt-12 text-sm text-muted-foreground text-center">
          Want a competitive analysis across all games in this developer&apos;s primary genre?{" "}
          <Link href="/pro" className="font-mono hover:text-foreground transition-colors" style={{ color: "var(--teal)" }}>
            Developer Intelligence (Pro) &rarr;
          </Link>
        </p>
      </div>
    </div>
  );
}

export const revalidate = 86400;
