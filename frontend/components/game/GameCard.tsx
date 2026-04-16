import Link from "next/link";
import Image from "next/image";
import { Gem } from "lucide-react";
import { EarlyAccessBadge } from "@/components/game/EarlyAccessBadge";
import { displayedReview } from "@/lib/review-display";
import type { Game } from "@/lib/types";

interface GameCardProps {
  game: Game;
}

export function GameCard({ game }: GameCardProps) {
  const href = `/games/${game.appid}/${game.slug}`;
  const displayed = displayedReview(game);
  // For ex-EA games we show the post-release score so it matches Steam's store UI.
  const score = displayed.count > 0 ? displayed.positivePct : null;
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
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
            className="object-cover transition-transform duration-500 group-hover:scale-105"
          />
        )}
        {game.is_early_access && (
          <div className="absolute top-2 left-2">
            <EarlyAccessBadge />
          </div>
        )}
        {Math.round((game.hidden_gem_score ?? 0) * 100) >= 70 && (
          <div
            className="absolute top-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono uppercase tracking-widest"
            style={{ background: "rgba(201,151,60,0.85)", color: "#0c0c0f" }}
          >
            <Gem className="w-2.5 h-2.5" />
            Gem
          </div>
        )}
      </div>
      <div className="p-4 flex-1 flex flex-col">
        <h3 className="font-serif text-base font-semibold text-foreground line-clamp-1 mb-1">
          {game.name}
        </h3>
        {game.developer && (
          <p className="text-sm text-muted-foreground font-mono mb-3 truncate">
            {game.developer}
          </p>
        )}
        <div className="mt-auto flex items-center gap-2">
          {score != null ? (
            <>
              <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${score}%`, background: scoreColor }}
                />
              </div>
              <span className="font-mono text-sm tabular-nums" style={{ color: scoreColor }}>
                {score}
              </span>
            </>
          ) : (
            displayed.count > 0 && (
              <span className="text-xs font-mono text-muted-foreground">
                {displayed.count.toLocaleString()}
                {" reviews "}
                <span style={{ opacity: 0.4, fontSize: "0.8em" }}>en</span>
              </span>
            )
          )}
        </div>
        {displayed.hasEarlyAccessHistory && !game.coming_soon && (
          <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground mt-2 opacity-70">
            {displayed.phase === "post_release"
              ? "ex-EA · post-release reviews only"
              : "ex-EA · no post-release reviews yet"}
          </p>
        )}
      </div>
    </Link>
  );
}
