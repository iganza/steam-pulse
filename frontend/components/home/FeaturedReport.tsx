import Link from "next/link";
import { ArrowRight, ChevronRight } from "lucide-react";
import type { GenreInsights } from "@/lib/types";
import type { GameBasicsEntry } from "@/lib/api";

interface Props {
  insights: GenreInsights;
  strip: GameBasicsEntry[];
}

function steamHeaderFallback(appid: number): string {
  return `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`;
}

function StripTab({ game }: { game: GameBasicsEntry }) {
  const href = `/games/${game.appid}/${game.slug}`;
  const headerImage = game.header_image ?? steamHeaderFallback(game.appid);
  const hasSentiment =
    game.positive_pct !== null && game.review_count !== null;

  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-xl p-3 transition-colors hover:bg-secondary/40"
      style={{ border: "1px solid var(--border)" }}
    >
      <img
        src={headerImage}
        alt={game.name}
        loading="lazy"
        className="rounded-md object-cover flex-shrink-0"
        style={{ width: 96, height: 44 }}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground truncate">
          {game.name}
        </p>
        {hasSentiment && (
          <p className="text-xs font-mono text-muted-foreground truncate">
            {game.positive_pct}% positive ·{" "}
            {game.review_count!.toLocaleString()} reviews
          </p>
        )}
      </div>
      <ChevronRight
        className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors flex-shrink-0"
      />
    </Link>
  );
}

export function FeaturedReport({ insights, strip }: Props) {
  const href = `/genre/${insights.slug}`;
  const positivePct = Math.round(insights.avg_positive_pct);
  const medianReviews = insights.median_review_count.toLocaleString();
  const showStrip = strip.length > 0;

  return (
    <section
      className="rounded-2xl p-8 md:p-10"
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
      }}
    >
      <p className="text-xs font-mono uppercase tracking-widest mb-4 text-teal">
        Featured Report · New
      </p>

      <h2
        className="font-serif text-2xl md:text-3xl font-bold mb-4 leading-tight"
        style={{ letterSpacing: "-0.02em" }}
      >
        What {insights.display_name} Players Want, Hate, and Praise
      </h2>

      <p className="text-base text-muted-foreground mb-6 max-w-2xl">
        A whole-niche synthesis of every player review across the
        {" "}{insights.display_name.toLowerCase()} catalog: friction
        patterns, wishlist gaps, benchmark games, and ranked dev priorities.
      </p>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mb-6 text-eyebrow">
        <span>{insights.input_count} games synthesised</span>
        <span>·</span>
        <span>{positivePct}% positive</span>
        <span>·</span>
        <span>median {medianReviews} reviews/game</span>
      </div>

      <Link
        href={href}
        className="group inline-flex items-center gap-2 text-sm font-mono uppercase tracking-widest text-foreground hover:gap-3 transition-all"
      >
        Read the free synthesis
        <ArrowRight className="w-4 h-4" />
      </Link>

      {showStrip && (
        <>
          <hr
            className="my-8"
            style={{ borderColor: "var(--border)" }}
          />
          <h3 className="font-serif text-xl font-semibold mb-4">
            Game intelligence in action
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {strip.map((game) => (
              <StripTab key={game.appid} game={game} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
