"use client";

import Image from "next/image";
import Link from "next/link";
import { EarlyAccessBadge } from "@/components/game/EarlyAccessBadge";
import { HiddenGemBadge } from "@/components/game/HiddenGemBadge";
import { DeckCompatibilityBadge } from "@/components/game/DeckCompatibilityBadge";
import { slugify } from "@/lib/format";

interface GameHeroProps {
  name: string;
  headerImage?: string;
  genres?: string[];
  isEarlyAccess?: boolean;
  deckCompatibility?: number | null;
  deckTestResults?: Array<{ display_type: number; loc_token: string }>;
  /** 0.0–1.0 from the report; null when the game hasn't been analyzed yet.
   *  Badge is rendered only when a score is available. */
  hiddenGemScore: number | null;
  positivePct: number | null;
  reviewScoreDesc: string | null;
  developer?: string;
  developerSlug?: string;
  publisher?: string;
  publisherSlug?: string;
}

export function GameHero({
  name,
  headerImage,
  genres,
  isEarlyAccess,
  deckCompatibility,
  deckTestResults,
  hiddenGemScore,
  positivePct,
  reviewScoreDesc,
  developer,
  developerSlug,
  publisher,
  publisherSlug,
}: GameHeroProps) {
  // Hide publisher credit when it matches developer (self-published titles),
  // matching the Steam store convention.
  const showPublisher = Boolean(
    publisher && (publisherSlug ? publisherSlug !== developerSlug : publisher !== developer),
  );
  return (
    <div className="relative h-[50vh] min-h-[360px] overflow-hidden">
      {headerImage ? (
        <Image
          src={headerImage}
          alt={name}
          fill
          className="object-cover object-top"
          priority
        />
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-secondary to-background" />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-background via-background/60 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-r from-background/80 via-transparent to-transparent" />

      <div className="absolute bottom-0 left-0 right-0 px-6 pb-8 max-w-4xl">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {genres?.map((g) => (
            <Link
              key={g}
              href={`/genre/${slugify(g)}`}
              className="text-xs uppercase tracking-widest font-mono px-2 py-0.5 rounded bg-teal/10 border border-teal/20 text-teal"
            >
              {g}
            </Link>
          ))}
        </div>
        <h1
          className="font-serif text-h1 font-bold text-foreground leading-tight mb-2"
          style={{ letterSpacing: "-0.03em" }}
        >
          {name}
        </h1>
        {(developer || publisher) && (
          <p className="text-sm text-muted-foreground font-mono mb-3">
            {developer && (
              <>
                by{" "}
                <Link
                  href={`/developer/${developerSlug ?? slugify(developer)}`}
                  className="hover:underline text-teal"
                >
                  {developer}
                </Link>
              </>
            )}
            {showPublisher && (
              <>
                {developer && <span className="mx-1.5">·</span>}
                published by{" "}
                <Link
                  href={`/publisher/${publisherSlug ?? slugify(publisher!)}`}
                  className="hover:underline text-teal"
                >
                  {publisher}
                </Link>
              </>
            )}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {isEarlyAccess && <EarlyAccessBadge />}
          {hiddenGemScore != null && (
            <HiddenGemBadge score={Math.round(hiddenGemScore * 100)} />
          )}
          <DeckCompatibilityBadge
            compatibility={deckCompatibility}
            testResults={deckTestResults}
          />
          {/* Steam-sourced sentiment chip — never fabricated when Steam's
              label is absent. */}
          {reviewScoreDesc && (
            <span
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono uppercase tracking-widest"
              style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
              }}
              title={
                positivePct != null
                  ? `${positivePct}% positive on Steam`
                  : "Source: Steam"
              }
            >
              <span aria-hidden>👍</span>
              <span>Steam · {reviewScoreDesc}</span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
