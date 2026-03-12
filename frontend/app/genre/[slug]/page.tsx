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
    title: `${name} Games`,
    description: `AI-analyzed ${name} games on Steam — sentiment, player insights, and hidden gems.`,
  };
}

function GameRow({ game }: { game: Game }) {
  const score = game.sentiment_score ?? game.positive_pct;
  const scoreColor =
    (score ?? 0) >= 75 ? "#22c55e" : (score ?? 0) >= 50 ? "#f59e0b" : "#ef4444";

  return (
    <Link
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
        <p className="font-serif text-sm font-semibold text-foreground group-hover:text-teal-300 transition-colors truncate">
          {game.name}
        </p>
        {game.developer && (
          <p className="text-[11px] text-muted-foreground font-mono truncate">{game.developer}</p>
        )}
      </div>
      {score != null && (
        <span className="font-mono text-sm tabular-nums flex-shrink-0" style={{ color: scoreColor }}>
          {score}
        </span>
      )}
    </Link>
  );
}

export default async function GenrePage({ params }: Props) {
  const { slug } = await params;
  const name = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  let games: Game[] = [];
  try {
    games = await getGames({ genre: slug, sort: "review_count", limit: 50 });
  } catch {
    notFound();
  }

  return (
    <div className="min-h-screen bg-background max-w-3xl mx-auto px-6 py-16">
      <Link
        href="/"
        className="font-mono text-xs text-muted-foreground hover:text-foreground transition-colors uppercase tracking-widest mb-8 inline-block"
      >
        ← Home
      </Link>
      <h1
        className="font-serif text-4xl font-bold mb-2"
        style={{ letterSpacing: "-0.03em" }}
      >
        {name}
      </h1>
      <p className="text-sm text-muted-foreground font-mono mb-10">
        {games.length} games analyzed
      </p>
      <div className="space-y-3">
        {games.map((game) => (
          <GameRow key={game.appid} game={game} />
        ))}
        {games.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12">
            No games found for this genre yet.
          </p>
        )}
      </div>
    </div>
  );
}

// ISR daily
export const revalidate = 86400;
