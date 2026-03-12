import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { notFound } from "next/navigation";
import { getGames } from "@/lib/api";
import type { Game } from "@/lib/types";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return {
    title: `${name} — Developer Profile`,
    description: `All Steam games by ${name} — AI-analyzed player sentiment across their catalog.`,
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
    games = await getGames({ developer: slug, sort: "review_count", limit: 100 });
  } catch {
    notFound();
  }

  const avgScore = avg(games, "sentiment_score") ?? avg(games, "positive_pct");
  const totalReviews = games.reduce((a, g) => a + (g.review_count ?? 0), 0);

  return (
    <div className="min-h-screen bg-background max-w-3xl mx-auto px-6 py-16">
      <Link
        href="/"
        className="font-mono text-xs text-muted-foreground hover:text-foreground transition-colors uppercase tracking-widest mb-8 inline-block"
      >
        ← Home
      </Link>

      {/* Developer header */}
      <h1
        className="font-serif text-4xl font-bold mb-6"
        style={{ letterSpacing: "-0.03em" }}
      >
        {name}
      </h1>

      {/* Cross-game stats */}
      <div className="grid grid-cols-3 gap-4 mb-10">
        {[
          { label: "Games", value: games.length },
          { label: "Total Reviews", value: totalReviews.toLocaleString() },
          { label: "Avg Sentiment", value: avgScore != null ? `${avgScore}` : "—" },
        ].map((s) => (
          <div
            key={s.label}
            className="p-4 rounded-xl"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-1">
              {s.label}
            </p>
            <p className="font-mono text-lg font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Sentiment across catalog */}
      {games.length > 0 && (
        <div className="mb-6 p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
          <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-3">
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
                    className="text-xs font-mono truncate w-40 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
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
                      <span className="font-mono text-xs tabular-nums w-6 text-right" style={{ color }}>
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
      <div className="space-y-3">
        {games.map((game) => (
          <Link
            key={game.appid}
            href={`/games/${game.appid}/${game.slug}`}
            className="group flex items-center gap-4 p-4 rounded-xl transition-all hover:scale-[1.01]"
            style={{ background: "var(--card)", border: "1px solid var(--border)" }}
          >
            {game.header_image && (
              <div className="relative w-24 h-11 rounded overflow-hidden flex-shrink-0">
                <Image src={game.header_image} alt={game.name} fill className="object-cover" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="font-serif text-sm font-semibold group-hover:text-teal-300 transition-colors truncate">
                {game.name}
              </p>
              {game.release_date && (
                <p className="text-[11px] text-muted-foreground font-mono">
                  {new Date(game.release_date).getFullYear()}
                </p>
              )}
            </div>
            {game.review_count != null && (
              <span className="text-[11px] font-mono text-muted-foreground flex-shrink-0">
                {game.review_count.toLocaleString()} reviews
              </span>
            )}
          </Link>
        ))}
        {games.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12">
            No games found for this developer.
          </p>
        )}
      </div>
    </div>
  );
}

export const revalidate = 86400;
