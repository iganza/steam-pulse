"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { ArrowRight } from "lucide-react";
import { getScoreColor } from "@/lib/styles";

export interface ShowcaseEntry {
  appid: number;
  name: string;
  slug: string;
  header_image: string | null;
  positive_pct: number | null;
  one_liner: string | null;
  top_strength: string | null;
  top_friction: string | null;
  reviews_analyzed: number | null;
}

interface Props {
  entries: ShowcaseEntry[];
}

export function FeaturedAnalysesShowcase({ entries }: Props) {
  const [active, setActive] = useState(0);
  if (entries.length === 0) return null;

  const e = entries[active] ?? entries[0];
  const score = e.positive_pct;
  const scoreColor = getScoreColor(score ?? 0);
  const href = `/games/${e.appid}/${e.slug}`;

  return (
    <section aria-labelledby="featured-analyses-heading">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <h2
          id="featured-analyses-heading"
          className="font-serif text-lg font-semibold"
        >
          Featured analyses
        </h2>
        <div
          role="tablist"
          aria-label="Featured analyses"
          className="flex flex-wrap gap-2"
        >
          {entries.map((entry, i) => {
            const isActive = i === active;
            return (
              <button
                key={entry.appid}
                role="tab"
                aria-selected={isActive}
                aria-controls="featured-analyses-panel"
                id={`showcase-tab-${entry.appid}`}
                onClick={() => setActive(i)}
                className="px-3 py-1.5 rounded-full text-xs font-mono uppercase tracking-widest transition-colors"
                style={{
                  background: isActive ? "var(--teal)" : "var(--card)",
                  color: isActive ? "var(--background)" : "var(--foreground)",
                  border: `1px solid ${isActive ? "var(--teal)" : "var(--border)"}`,
                }}
              >
                {entry.name}
              </button>
            );
          })}
        </div>
      </div>

      <div
        role="tabpanel"
        id="featured-analyses-panel"
        aria-labelledby={`showcase-tab-${e.appid}`}
        className="rounded-2xl overflow-hidden grid grid-cols-1 md:grid-cols-[40%_60%] gap-0"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <div className="relative aspect-[460/215] md:aspect-auto bg-secondary">
          <Image
            src={
              e.header_image ??
              `https://cdn.akamai.steamstatic.com/steam/apps/${e.appid}/header.jpg`
            }
            alt={e.name}
            fill
            sizes="(max-width: 768px) 100vw, 40vw"
            className="object-cover"
            priority={active === 0}
          />
        </div>

        <div className="p-5 flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="font-serif text-xl font-semibold text-foreground line-clamp-1">
              {e.name}
            </h3>
            {score != null && (
              <span
                className="shrink-0 font-mono text-xs tabular-nums"
                style={{ color: scoreColor }}
              >
                {score}% positive
              </span>
            )}
          </div>

          {e.one_liner && (
            <p className="font-serif text-sm italic text-foreground/90 leading-snug line-clamp-2">
              &ldquo;{e.one_liner}&rdquo;
            </p>
          )}

          <div className="flex flex-col gap-2">
            {e.top_strength && (
              <div>
                <p className="text-eyebrow mb-0.5" style={{ color: "var(--positive)" }}>
                  ✓ What works
                </p>
                <p className="text-xs text-foreground/85 leading-relaxed line-clamp-2">
                  {e.top_strength}
                </p>
              </div>
            )}
            {e.top_friction && (
              <div>
                <p className="text-eyebrow mb-0.5" style={{ color: "#f59e0b" }}>
                  ⚠ What hurts
                </p>
                <p className="text-xs text-foreground/85 leading-relaxed line-clamp-2">
                  {e.top_friction}
                </p>
              </div>
            )}
          </div>

          <div className="mt-auto pt-1 flex items-center justify-between gap-3 flex-wrap">
            {e.reviews_analyzed != null && (
              <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                Based on {e.reviews_analyzed.toLocaleString()} reviews
              </span>
            )}
            <Link
              href={href}
              className="inline-flex items-center gap-1 text-xs font-mono uppercase tracking-widest text-teal hover:underline"
            >
              Read full analysis <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
