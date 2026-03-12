"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  CheckCircle2,
  AlertCircle,
  Lightbulb,
  DoorOpen,
  Target,
  Swords,
  Users,
  Star,
  Calendar,
  DollarSign,
  BarChart3,
} from "lucide-react";
import type { GameReport, PreviewResponse } from "@/lib/types";
import { ScoreBar } from "@/components/game/ScoreBar";
import { HiddenGemBadge } from "@/components/game/HiddenGemBadge";
import { SectionLabel } from "@/components/game/SectionLabel";
import { PremiumUnlock } from "@/components/game/PremiumUnlock";

interface GameReportClientProps {
  preview: PreviewResponse;
  headerImage?: string;
  releaseDate?: string;
  developer?: string;
  priceUsd?: number | null;
  isFree?: boolean;
  genres?: string[];
}

function TrendIcon({ trend }: { trend: string }) {
  const lower = trend?.toLowerCase() ?? "";
  if (lower.includes("improv") || lower.includes("up") || lower.includes("positive"))
    return <TrendingUp className="w-4 h-4 text-positive" />;
  if (lower.includes("declin") || lower.includes("down") || lower.includes("negative"))
    return <TrendingDown className="w-4 h-4 text-destructive" />;
  return <Minus className="w-4 h-4 text-muted-foreground" />;
}

export function GameReportClient({
  preview,
  headerImage,
  releaseDate,
  developer,
  priceUsd,
  isFree,
  genres,
}: GameReportClientProps) {
  const [fullReport, setFullReport] = useState<GameReport | null>(null);

  const report = fullReport;
  const appid = preview.appid;

  const price = isFree ? "Free" : priceUsd ? `$${priceUsd.toFixed(2)}` : "—";

  // Placeholder premium content (visible blurred)
  const placeholderWishlist = [
    "Co-op or multiplayer support",
    "New biome with unique mechanics",
    "More endgame content and progression",
    "Modding tools and Steam Workshop",
    "Controller support improvements",
  ];
  const placeholderChurn = [
    "First hour: tutorial feels gate-heavy",
    "Hour 3–5: mid-game difficulty spike",
    "Post-completion: lack of replayability",
  ];
  const placeholderPriorities = [
    { action: "Fix save system reliability", why_it_matters: "Top complaint", frequency: "High", effort: "Low" },
    { action: "Add rebindable controls", why_it_matters: "Accessibility gap", frequency: "Medium", effort: "Low" },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* ── Hero ── */}
      <div className="relative h-[50vh] min-h-[360px] overflow-hidden">
        {headerImage ? (
          <Image
            src={headerImage}
            alt={preview.game_name}
            fill
            className="object-cover object-top"
            priority
          />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-secondary to-background" />
        )}
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/60 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-r from-background/80 via-transparent to-transparent" />

        {/* Nav */}
        <nav className="absolute top-0 left-0 right-0 flex items-center justify-between px-6 py-5">
          <Link
            href="/"
            className="font-mono text-sm text-muted-foreground hover:text-foreground transition-colors tracking-widest uppercase"
          >
            ← SteamPulse
          </Link>
          <a
            href={`https://store.steampowered.com/app/${appid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-xs text-muted-foreground hover:text-foreground transition-colors border border-border px-3 py-1.5 rounded"
          >
            Steam Store ↗
          </a>
        </nav>

        {/* Title block */}
        <div className="absolute bottom-0 left-0 right-0 px-6 pb-8 max-w-4xl">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {genres?.map((g) => (
              <Link
                key={g}
                href={`/genre/${g.toLowerCase().replace(/\s+/g, "-")}`}
                className="text-[10px] uppercase tracking-widest font-mono px-2 py-0.5 rounded"
                style={{
                  background: "rgba(45,185,212,0.1)",
                  border: "1px solid rgba(45,185,212,0.2)",
                  color: "var(--teal)",
                }}
              >
                {g}
              </Link>
            ))}
          </div>
          <h1
            className="font-serif text-4xl md:text-5xl font-bold text-foreground leading-tight mb-3"
            style={{ letterSpacing: "-0.03em" }}
          >
            {preview.game_name}
          </h1>
          <div className="flex flex-wrap items-center gap-3">
            <HiddenGemBadge
              score={report?.hidden_gem_score ?? 0}
            />
            <span
              className="inline-block px-3 py-1 rounded-full text-xs font-mono uppercase tracking-widest"
              style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
              }}
            >
              {preview.overall_sentiment}
            </span>
          </div>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="max-w-4xl mx-auto px-6 py-12 space-y-16">

        {/* Section 2 — The Verdict */}
        <section className="animate-fade-up stagger-1">
          <SectionLabel>The Verdict</SectionLabel>
          <blockquote
            className="font-serif text-2xl md:text-3xl text-foreground/90 leading-snug mb-8 italic"
            style={{ letterSpacing: "-0.01em" }}
          >
            &ldquo;{preview.one_liner}&rdquo;
          </blockquote>
          <ScoreBar score={preview.sentiment_score} />
        </section>

        {/* Section 3 — Quick Stats */}
        <section className="animate-fade-up stagger-2">
          <SectionLabel>Quick Stats</SectionLabel>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              {
                icon: <BarChart3 className="w-4 h-4" />,
                label: "Reviews",
                value: preview.appid ? "—" : "—",
              },
              {
                icon: <Calendar className="w-4 h-4" />,
                label: "Released",
                value: releaseDate
                  ? new Date(releaseDate).getFullYear().toString()
                  : "—",
              },
              {
                icon: <DollarSign className="w-4 h-4" />,
                label: "Price",
                value: price,
              },
              {
                icon: <Star className="w-4 h-4" />,
                label: "Developer",
                value: developer ?? "—",
              },
            ].map((stat) => (
              <div
                key={stat.label}
                className="p-4 rounded-xl"
                style={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  {stat.icon}
                  <span className="text-[10px] uppercase tracking-widest font-mono">
                    {stat.label}
                  </span>
                </div>
                <p className="font-mono text-sm font-medium truncate">
                  {stat.value}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Section 4 — Design Strengths */}
        <section className="animate-fade-up stagger-3">
          <SectionLabel>Design Strengths</SectionLabel>
          <ul className="space-y-3">
            {(report?.design_strengths ?? []).map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <CheckCircle2
                  className="w-4 h-4 mt-0.5 flex-shrink-0"
                  style={{ color: "var(--positive)" }}
                />
                <span className="text-sm text-foreground/80 leading-relaxed">
                  {item}
                </span>
              </li>
            ))}
            {!report && (
              <p className="text-sm text-muted-foreground italic">
                Analysis pending…
              </p>
            )}
          </ul>
        </section>

        {/* Section 5 — Gameplay Friction */}
        <section className="animate-fade-up stagger-4">
          <SectionLabel>Gameplay Friction</SectionLabel>
          <ul className="space-y-3">
            {(report?.gameplay_friction ?? []).map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <AlertCircle
                  className="w-4 h-4 mt-0.5 flex-shrink-0"
                  style={{ color: "var(--negative)" }}
                />
                <span className="text-sm text-foreground/80 leading-relaxed">
                  {item}
                </span>
              </li>
            ))}
            {!report && (
              <p className="text-sm text-muted-foreground italic">
                Analysis pending…
              </p>
            )}
          </ul>
        </section>

        {/* Section 6 — Audience Profile */}
        {(report?.audience_profile || preview.audience_profile) && (
          <section className="animate-fade-up stagger-5">
            <SectionLabel>Audience Profile</SectionLabel>
            <div className="grid md:grid-cols-2 gap-6">
              <div
                className="p-5 rounded-xl space-y-4"
                style={{
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                }}
              >
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-1">
                    Ideal Player
                  </p>
                  <p className="text-sm text-foreground/80">
                    {(report?.audience_profile ?? preview.audience_profile)?.ideal_player}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-1">
                    Casual Friendliness
                  </p>
                  <p className="text-sm text-foreground/80">
                    {(report?.audience_profile ?? preview.audience_profile)?.casual_friendliness}
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-2">
                    Player Archetypes
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(report?.audience_profile ?? preview.audience_profile)?.archetypes?.map(
                      (a) => (
                        <span
                          key={a}
                          className="text-xs px-2.5 py-1 rounded-full font-mono"
                          style={{
                            background: "rgba(45,185,212,0.08)",
                            border: "1px solid rgba(45,185,212,0.2)",
                            color: "var(--teal)",
                          }}
                        >
                          {a}
                        </span>
                      ),
                    )}
                  </div>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-2">
                    Not For
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(report?.audience_profile ?? preview.audience_profile)?.not_for?.map(
                      (n) => (
                        <span
                          key={n}
                          className="text-xs px-2.5 py-1 rounded-full font-mono"
                          style={{
                            background: "rgba(239,68,68,0.08)",
                            border: "1px solid rgba(239,68,68,0.15)",
                            color: "rgba(239,68,68,0.8)",
                          }}
                        >
                          {n}
                        </span>
                      ),
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Section 7 — Sentiment Trend */}
        {report && (
          <section className="animate-fade-up stagger-6">
            <SectionLabel>Sentiment Trend</SectionLabel>
            <div
              className="p-5 rounded-xl flex items-start gap-4"
              style={{
                background: "var(--card)",
                border: "1px solid var(--border)",
              }}
            >
              <TrendIcon trend={report.sentiment_trend} />
              <div>
                <p className="text-sm font-mono font-medium mb-1">
                  {report.sentiment_trend}
                </p>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {report.sentiment_trend_note}
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Section 8 — Genre Context */}
        {report?.genre_context && (
          <section>
            <SectionLabel>Genre Context</SectionLabel>
            <p className="text-sm text-foreground/80 leading-relaxed">
              {report.genre_context}
            </p>
          </section>
        )}

        {/* ── PREMIUM SECTIONS 9–11 ── */}
        <section>
          <PremiumUnlock appid={appid} onUnlock={setFullReport}>
            <div className="space-y-12 p-6 rounded-xl"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}>

              {/* Section 9 — Player Wishlist */}
              <div>
                <SectionLabel premium>Player Wishlist</SectionLabel>
                <ul className="space-y-3">
                  {(report?.player_wishlist ?? placeholderWishlist).map((item, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <Lightbulb
                        className="w-4 h-4 mt-0.5 flex-shrink-0"
                        style={{ color: "var(--gem)" }}
                      />
                      <span className="text-sm text-foreground/80 leading-relaxed">
                        {item}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Section 10 — Churn Triggers */}
              <div>
                <SectionLabel premium>Churn Triggers</SectionLabel>
                <ul className="space-y-3">
                  {(report?.churn_triggers ?? placeholderChurn).map((item, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <DoorOpen
                        className="w-4 h-4 mt-0.5 flex-shrink-0"
                        style={{ color: "var(--negative)" }}
                      />
                      <span className="text-sm text-foreground/80 leading-relaxed">
                        {item}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Section 11 — Developer Priorities */}
              <div>
                <SectionLabel premium>Developer Priorities</SectionLabel>
                <div className="space-y-4">
                  {(report?.dev_priorities ?? placeholderPriorities).map((p, i) => (
                    <div
                      key={i}
                      className="p-4 rounded-lg"
                      style={{
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div className="flex items-start gap-3 mb-2">
                        <span
                          className="font-mono text-xs px-1.5 py-0.5 rounded mt-0.5 flex-shrink-0"
                          style={{
                            background: "rgba(45,185,212,0.1)",
                            color: "var(--teal)",
                          }}
                        >
                          #{i + 1}
                        </span>
                        <p className="text-sm font-medium text-foreground flex items-center gap-2">
                          <Target className="w-3.5 h-3.5 flex-shrink-0" style={{ color: "var(--teal)" }} />
                          {p.action}
                        </p>
                      </div>
                      <p className="text-xs text-muted-foreground ml-8 mb-3 leading-relaxed">
                        {p.why_it_matters}
                      </p>
                      <div className="flex gap-4 ml-8">
                        <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                          Freq: <span className="text-foreground/60">{p.frequency}</span>
                        </span>
                        <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                          Effort: <span className="text-foreground/60">{p.effort}</span>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </PremiumUnlock>
        </section>

        {/* Section 12 — Competitive Context */}
        {report?.competitive_context && report.competitive_context.length > 0 && (
          <section>
            <SectionLabel>Competitive Context</SectionLabel>
            <div className="space-y-3">
              {report.competitive_context.map((c, i) => (
                <div
                  key={i}
                  className="p-4 rounded-xl flex items-start gap-4"
                  style={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <Swords className="w-4 h-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-mono font-medium text-foreground">
                        {c.game}
                      </span>
                      <span
                        className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full"
                        style={{
                          background: "rgba(255,255,255,0.05)",
                          color: "var(--muted-foreground)",
                        }}
                      >
                        {c.comparison_sentiment}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {c.note}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Section 13 — Related / footer */}
        <section className="pt-8 border-t border-border">
          <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
            <Users className="w-3.5 h-3.5" />
            <span>
              Analysis based on{" "}
              {report?.total_reviews_analyzed?.toLocaleString() ?? "—"} reviews
            </span>
            {report?.last_analyzed && (
              <span className="ml-auto">
                Updated{" "}
                {new Date(report.last_analyzed).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </span>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
