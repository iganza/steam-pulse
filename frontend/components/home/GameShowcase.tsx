"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { SentimentTimeline } from "@/components/game/SentimentTimeline";
import type { TimelineEntry, AudienceOverlapEntry, GameReport } from "@/lib/types";

export interface ShowcaseGame {
  appid: number;
  slug: string;
  gameName: string;
  headerImage: string;
  report: GameReport;
  timeline: TimelineEntry[];
  overlaps: AudienceOverlapEntry[];
  totalReviewers: number;
}

interface GameShowcaseProps {
  games: ShowcaseGame[];
}

function ShowcaseContent({ game }: { game: ShowcaseGame }) {
  const topOverlaps = game.overlaps.slice(0, 4);
  const maxOverlap = Math.max(...topOverlaps.map((e) => e.overlap_pct)) || 1;

  return (
    <div className="grid md:grid-cols-2 gap-0">
      {/* Left — game info + report excerpt */}
      <div className="p-6 flex flex-col">
        <div className="flex items-start gap-4 mb-4">
          <img
            src={game.headerImage}
            alt={game.gameName}
            className="rounded-lg object-cover flex-shrink-0"
            style={{ width: 120, height: 56 }}
          />
          <div>
            <h3 className="font-serif text-lg font-semibold leading-tight">
              {game.gameName}
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              {game.report.total_reviews_analyzed.toLocaleString()} reviews analyzed
            </p>
          </div>
        </div>

        <p className="text-sm text-foreground/80 italic mb-4">
          &ldquo;{game.report.one_liner}&rdquo;
        </p>

        <div className="space-y-2 mb-4 flex-1">
          <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
            Design strengths
          </p>
          {game.report.design_strengths.slice(0, 3).map((s) => (
            <p key={s} className="text-sm text-foreground/70 line-clamp-1">
              <span style={{ color: "var(--positive)" }}>+</span> {s}
            </p>
          ))}
          {game.report.gameplay_friction.length > 0 && (
            <>
              <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground mt-3">
                Gameplay friction
              </p>
              {game.report.gameplay_friction.slice(0, 2).map((f) => (
                <p key={f} className="text-sm text-foreground/70 line-clamp-1">
                  <span style={{ color: "var(--negative)" }}>−</span> {f}
                </p>
              ))}
            </>
          )}
        </div>

        <div className="flex items-center gap-4 mt-auto pt-4">
          <Link
            href={`/games/${game.appid}/${game.slug}`}
            className="flex items-center gap-1 text-sm font-mono"
            style={{ color: "var(--teal)" }}
          >
            Explore this game <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
      </div>

      {/* Right — charts */}
      <div
        className="p-6 flex flex-col gap-6"
        style={{ borderLeft: "1px solid var(--border)" }}
      >
        <SentimentTimeline timeline={game.timeline} />

        {topOverlaps.length > 0 && (
          <div>
            <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-3">
              Audience overlap &middot; {game.totalReviewers.toLocaleString()} reviewers
            </p>
            <div className="flex flex-col gap-2">
              {topOverlaps.map((entry) => (
                <div key={entry.appid} className="flex items-center gap-2">
                  <span className="text-xs truncate flex-1 text-muted-foreground">
                    {entry.name}
                  </span>
                  <div
                    className="h-1.5 rounded-full flex-shrink-0"
                    style={{
                      width: `${Math.max(20, (entry.overlap_pct / maxOverlap) * 50)}%`,
                      background: "var(--teal)",
                      opacity: 0.7,
                    }}
                  />
                  <span className="text-xs font-mono text-muted-foreground flex-shrink-0 w-10 text-right">
                    {entry.overlap_pct.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function GameShowcase({ games }: GameShowcaseProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  if (games.length === 0) return null;

  const activeGame = games[activeIndex];

  return (
    <section>
      <h2 className="font-serif text-xl font-semibold mb-6">
        Game Intelligence in Action
      </h2>
      <div
        className="rounded-xl overflow-hidden"
        style={{
          background: "var(--card)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Tab bar */}
        {games.length > 1 && (
          <div
            role="tablist"
            aria-label="Showcase games"
            className="flex border-b"
            style={{ borderColor: "var(--border)" }}
          >
            {games.map((game, i) => (
              <button
                key={game.appid}
                type="button"
                role="tab"
                id={`showcase-tab-${game.appid}`}
                aria-selected={i === activeIndex}
                aria-controls={`showcase-panel-${game.appid}`}
                tabIndex={i === activeIndex ? 0 : -1}
                onClick={() => setActiveIndex(i)}
                onKeyDown={(event) => {
                  let nextIndex = i;
                  switch (event.key) {
                    case "ArrowRight":
                      nextIndex = (i + 1) % games.length;
                      break;
                    case "ArrowLeft":
                      nextIndex = (i - 1 + games.length) % games.length;
                      break;
                    case "Home":
                      nextIndex = 0;
                      break;
                    case "End":
                      nextIndex = games.length - 1;
                      break;
                    default:
                      return;
                  }
                  event.preventDefault();
                  setActiveIndex(nextIndex);
                  document
                    .getElementById(`showcase-tab-${games[nextIndex].appid}`)
                    ?.focus();
                }}
                className="relative px-5 py-3 text-sm font-medium transition-colors"
                style={{
                  color: i === activeIndex ? "var(--foreground)" : "var(--muted-foreground)",
                }}
              >
                {game.gameName}
                {i === activeIndex && (
                  <span
                    className="absolute bottom-0 left-0 right-0 h-0.5"
                    style={{ background: "var(--teal)" }}
                  />
                )}
              </button>
            ))}
          </div>
        )}

        <div
          role="tabpanel"
          id={`showcase-panel-${activeGame.appid}`}
          aria-labelledby={`showcase-tab-${activeGame.appid}`}
        >
          <ShowcaseContent game={activeGame} />
        </div>
      </div>
    </section>
  );
}
