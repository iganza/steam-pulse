import Link from "next/link";
import Image from "next/image";
import { Search, Gem, TrendingUp, ChevronRight } from "lucide-react";
import { getGames, getGenres } from "@/lib/api";
import type { Game } from "@/lib/types";

function GameCard({ game }: { game: Game }) {
  const href = `/games/${game.appid}/${game.slug}`;
  const score = game.sentiment_score ?? game.positive_pct;
  const scoreColor =
    (score ?? 0) >= 75 ? "#22c55e" : (score ?? 0) >= 50 ? "#f59e0b" : "#ef4444";

  return (
    <Link
      href={href}
      className="group flex flex-col rounded-xl overflow-hidden transition-all duration-300 hover:scale-[1.02]"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <div className="relative aspect-[460/215] overflow-hidden bg-secondary">
        {game.header_image && (
          <Image
            src={game.header_image}
            alt={game.name}
            fill
            className="object-cover transition-transform duration-500 group-hover:scale-105"
          />
        )}
        {(game.hidden_gem_score ?? 0) >= 70 && (
          <div
            className="absolute top-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-widest"
            style={{ background: "rgba(201,151,60,0.85)", color: "#0c0c0f" }}
          >
            <Gem className="w-2.5 h-2.5" />
            Gem
          </div>
        )}
      </div>
      <div className="p-4 flex-1 flex flex-col">
        <h3 className="font-serif text-sm font-semibold text-foreground line-clamp-1 mb-1">
          {game.name}
        </h3>
        {game.developer && (
          <p className="text-[11px] text-muted-foreground font-mono mb-3 truncate">
            {game.developer}
          </p>
        )}
        {score != null && (
          <div className="mt-auto flex items-center gap-2">
            <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${score}%`, background: scoreColor }}
              />
            </div>
            <span className="font-mono text-xs tabular-nums" style={{ color: scoreColor }}>
              {score}
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}

export default async function HomePage() {
  const [trending, hiddenGems, genres] = await Promise.allSettled([
    getGames({ sort: "review_count", limit: 6 }),
    getGames({ sort: "hidden_gem_score", limit: 6 }),
    getGenres(),
  ]);

  const trendingGames: Game[] =
    trending.status === "fulfilled" ? trending.value : [];
  const gemGames: Game[] =
    hiddenGems.status === "fulfilled" ? hiddenGems.value : [];
  const genreList =
    genres.status === "fulfilled" ? genres.value.slice(0, 12) : [];

  return (
    <div className="min-h-screen bg-background">
      {/* ── Masthead ── */}
      <header className="relative overflow-hidden">
        <div
          className="absolute inset-0 opacity-30 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(45,185,212,0.15), transparent)",
          }}
        />
        <div className="relative max-w-5xl mx-auto px-6 pt-20 pb-16">
          <div className="max-w-2xl">
            <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-muted-foreground mb-4">
              AI Game Intelligence
            </p>
            <h1
              className="font-serif text-5xl md:text-6xl font-bold text-foreground mb-5 leading-[1.05]"
              style={{ letterSpacing: "-0.03em" }}
            >
              What players really
              <br />
              <span style={{ color: "var(--teal)" }}>think</span> about your game.
            </h1>
            <p className="text-base text-muted-foreground leading-relaxed mb-8 max-w-lg">
              AI-synthesized review intelligence for every Steam game. Understand
              sentiment, friction, and player needs — before your competitors do.
            </p>
            <form action="/search" className="relative max-w-xl">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
              <input
                name="q"
                type="text"
                placeholder="Search by game name or App ID…"
                className="w-full pl-11 pr-4 py-3.5 rounded-xl bg-card border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-400/20 transition-all"
              />
            </form>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 pb-24 space-y-20">
        {/* ── Trending ── */}
        {trendingGames.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4" style={{ color: "var(--teal)" }} />
                <h2 className="font-serif text-xl font-semibold">Most Reviewed</h2>
              </div>
              <Link
                href="/trending"
                className="flex items-center gap-1 text-xs font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
              >
                See all <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {trendingGames.map((game) => (
                <GameCard key={game.appid} game={game} />
              ))}
            </div>
          </section>
        )}

        {/* ── Hidden Gems ── */}
        {gemGames.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2">
                <Gem className="w-4 h-4" style={{ color: "var(--gem)" }} />
                <h2 className="font-serif text-xl font-semibold">Hidden Gems</h2>
              </div>
              <Link
                href="/hidden-gems"
                className="flex items-center gap-1 text-xs font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
              >
                See all <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {gemGames.map((game) => (
                <GameCard key={game.appid} game={game} />
              ))}
            </div>
          </section>
        )}

        {/* ── Genre Grid ── */}
        {genreList.length > 0 && (
          <section>
            <h2 className="font-serif text-xl font-semibold mb-6">Browse by Genre</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {genreList.map((genre) => (
                <Link
                  key={genre.id}
                  href={`/genre/${genre.slug}`}
                  className="group px-4 py-3 rounded-xl text-sm font-mono transition-all duration-200 hover:scale-[1.02]"
                  style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                >
                  <span className="text-foreground/80 group-hover:text-foreground transition-colors">
                    {genre.name}
                  </span>
                  {genre.game_count != null && (
                    <span className="block text-[10px] text-muted-foreground mt-0.5">
                      {genre.game_count.toLocaleString()} games
                    </span>
                  )}
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* ── Empty state ── */}
        {trendingGames.length === 0 && gemGames.length === 0 && (
          <div className="text-center py-20">
            <p className="font-mono text-sm text-muted-foreground mb-2">
              No games in the database yet.
            </p>
            <p className="text-xs text-muted-foreground">
              Run{" "}
              <code className="px-1.5 py-0.5 rounded bg-secondary font-mono text-[11px]">
                poetry run python scripts/seed.py --limit 500
              </code>{" "}
              to seed the catalog.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

export const revalidate = 3600;
