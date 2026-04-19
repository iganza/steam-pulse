"use client";

import Link from "next/link";
import { SectionLabel } from "@/components/game/SectionLabel";
import type { RelatedAnalyzedGame } from "@/lib/types";

interface RelatedAnalyzedGamesProps {
  games: RelatedAnalyzedGame[];
}

export function RelatedAnalyzedGames({ games }: RelatedAnalyzedGamesProps) {
  if (games.length === 0) return null;

  return (
    <section data-testid="related-analyzed-games">
      <SectionLabel>More games like this</SectionLabel>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {games.map((g) => (
          <Link
            key={g.appid}
            href={`/games/${g.appid}/${g.slug}`}
            className="block rounded-xl border border-border p-4 transition-colors hover:border-teal-400/40"
            style={{ background: "var(--card)" }}
          >
            <div className="flex items-start gap-3">
              {g.header_image && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={g.header_image}
                  alt=""
                  className="w-20 h-auto rounded-md flex-shrink-0"
                  loading="lazy"
                />
              )}
              <div className="min-w-0 flex-1">
                <p className="font-mono text-sm font-medium truncate">{g.name}</p>
                {g.positive_pct != null && (
                  <p className="mt-1 text-xs font-mono" style={{ color: "var(--teal)" }}>
                    {g.positive_pct}% positive
                  </p>
                )}
                {g.one_liner && (
                  <p className="mt-2 text-xs text-muted-foreground font-mono line-clamp-2">
                    {g.one_liner}
                  </p>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
