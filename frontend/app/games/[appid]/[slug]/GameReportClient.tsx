"use client";

import { useState, useEffect } from "react";
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
  Clock,
  Zap,
} from "lucide-react";
import type { GameReport, ReviewStats, Benchmarks } from "@/lib/types";
import { getReviewStats, getBenchmarks } from "@/lib/api";
import { ScoreBar } from "@/components/game/ScoreBar";
import { HiddenGemBadge } from "@/components/game/HiddenGemBadge";
import { SectionLabel } from "@/components/game/SectionLabel";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import {
  SentimentTimeline,
  SentimentTimelineSkeleton,
} from "@/components/game/SentimentTimeline";
import {
  PlaytimeChart,
  PlaytimeChartSkeleton,
  computePlaytimeInsight,
} from "@/components/game/PlaytimeChart";
import { CompetitiveBenchmark } from "@/components/game/CompetitiveBenchmark";

interface GameReportClientProps {
  report: GameReport | null;
  appid: number;
  gameName?: string;
  headerImage?: string;
  releaseDate?: string;
  developer?: string;
  priceUsd?: number | null;
  isFree?: boolean;
  genres?: string[];
  tags?: string[];
  shortDesc?: string;
  reviewCount?: number;
}

function TrendIcon({ trend }: { trend: string }) {
  const lower = trend?.toLowerCase() ?? "";
  if (lower.includes("improv") || lower.includes("up") || lower.includes("positive"))
    return <TrendingUp className="w-4 h-4 text-positive" />;
  if (lower.includes("declin") || lower.includes("down") || lower.includes("negative"))
    return <TrendingDown className="w-4 h-4 text-destructive" />;
  return <Minus className="w-4 h-4 text-muted-foreground" />;
}

function slugify(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function scoreContextSentence(score: number): string {
  if (score >= 95) return "Overwhelmingly Positive — fewer than 5% of Steam games with 1,000+ reviews achieve this.";
  if (score >= 80) return "Very Positive — this puts the game in the top 30% of all reviewed games on Steam.";
  if (score >= 70) return "Mostly Positive — above the median for reviewed Steam games.";
  if (score >= 50) return "Mixed — roughly half of players recommend it.";
  return "Mostly Negative — significant player dissatisfaction.";
}

function momentumLabel(reviewsLast30: number, reviewsPerDay: number): { label: string; color: string } {
  const expected = reviewsPerDay * 30;
  if (expected <= 0) return { label: "—", color: "var(--muted-foreground)" };
  const ratio = reviewsLast30 / expected;
  if (ratio >= 1.2) return { label: "Gaining momentum", color: "#22c55e" };
  if (ratio >= 0.8) return { label: "Steady", color: "var(--muted-foreground)" };
  return { label: "Slowing", color: "#f59e0b" };
}

const isPro = true; // TODO: wire to auth

export function GameReportClient({
  report,
  appid,
  gameName,
  headerImage,
  releaseDate,
  developer,
  priceUsd,
  isFree,
  genres,
  tags,
  shortDesc,
  reviewCount,
}: GameReportClientProps) {
  const [reviewStats, setReviewStats] = useState<ReviewStats | null>(null);
  const [benchmarks, setBenchmarks] = useState<Benchmarks | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [stats, bench] = await Promise.all([
          getReviewStats(appid),
          report ? getBenchmarks(appid).catch(() => null) : Promise.resolve(null),
        ]);
        setReviewStats(stats);
        if (bench) setBenchmarks(bench);
      } catch {
        // charts simply won't render
      } finally {
        setStatsLoading(false);
      }
    };
    load();
  }, [appid, report]);

  const name = report?.game_name ?? gameName ?? "Game Report";
  const price = isFree ? "Free" : priceUsd ? `$${priceUsd.toFixed(2)}` : "\u2014";
  const primaryGenre = genres?.[0];

  const breadcrumbItems = [
    { label: "Home", href: "/" },
    ...(primaryGenre
      ? [{ label: primaryGenre, href: `/genre/${slugify(primaryGenre)}` }]
      : []),
    { label: name },
  ];

  // Unanalyzed game state
  if (!report) {
    return (
      <div className="min-h-screen bg-background">
        {/* Hero */}
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
              {name}
            </h1>
          </div>
        </div>

        <div className="max-w-4xl mx-auto px-6 py-12 space-y-16">
          <Breadcrumbs items={breadcrumbItems} />

          {/* Quick Stats */}
          <section>
            <SectionLabel>Quick Stats</SectionLabel>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  <BarChart3 className="w-4 h-4" />
                  <span className="text-[10px] uppercase tracking-widest font-mono">Reviews</span>
                </div>
                <p className="font-mono text-sm font-medium truncate">{reviewCount?.toLocaleString() ?? "—"}</p>
              </div>
              <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  <Calendar className="w-4 h-4" />
                  <span className="text-[10px] uppercase tracking-widest font-mono">Released</span>
                </div>
                {releaseDate ? (
                  <Link href={`/search?year_from=${new Date(releaseDate).getFullYear()}&year_to=${new Date(releaseDate).getFullYear()}`} className="font-mono text-sm font-medium hover:underline" style={{ color: "var(--teal)" }}>
                    {new Date(releaseDate).getFullYear()}
                  </Link>
                ) : <p className="font-mono text-sm font-medium">—</p>}
              </div>
              <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  <DollarSign className="w-4 h-4" />
                  <span className="text-[10px] uppercase tracking-widest font-mono">Price</span>
                </div>
                <p className="font-mono text-sm font-medium truncate">{price}</p>
              </div>
              <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  <Star className="w-4 h-4" />
                  <span className="text-[10px] uppercase tracking-widest font-mono">Developer</span>
                </div>
                {developer ? (
                  <Link href={`/developer/${slugify(developer)}`} className="font-mono text-sm font-medium hover:underline truncate block" style={{ color: "var(--teal)" }}>
                    {developer}
                  </Link>
                ) : <p className="font-mono text-sm font-medium">—</p>}
              </div>
              {/* Review Velocity card */}
              <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div className="flex items-center gap-2 text-muted-foreground mb-2">
                  <Zap className="w-4 h-4" />
                  <span className="text-[10px] uppercase tracking-widest font-mono">Velocity</span>
                </div>
                {statsLoading ? (
                  <div className="h-4 bg-secondary rounded animate-pulse w-20" />
                ) : reviewStats ? (
                  <>
                    <p className="font-mono text-sm font-medium">
                      {reviewStats.review_velocity.reviews_per_day}/day
                    </p>
                    {(() => {
                      const m = momentumLabel(
                        reviewStats.review_velocity.reviews_last_30_days,
                        reviewStats.review_velocity.reviews_per_day
                      );
                      return (
                        <p className="text-[10px] font-mono mt-1" style={{ color: m.color }}>
                          {m.label}
                        </p>
                      );
                    })()}
                  </>
                ) : (
                  <p className="font-mono text-sm font-medium">—</p>
                )}
              </div>
            </div>
          </section>

          {/* Description */}
          {shortDesc && (
            <section>
              <SectionLabel>About</SectionLabel>
              <p className="text-sm text-foreground/80 leading-relaxed">{shortDesc}</p>
            </section>
          )}

          {/* Tags */}
          {tags && tags.length > 0 && (
            <section>
              <SectionLabel>Tags</SectionLabel>
              <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <Link
                    key={tag}
                    href={`/tag/${slugify(tag)}`}
                    className="text-xs px-2.5 py-1 rounded-full font-mono transition-colors hover:text-foreground"
                    style={{
                      background: "rgba(45,185,212,0.08)",
                      border: "1px solid rgba(45,185,212,0.2)",
                      color: "var(--teal)",
                    }}
                  >
                    {tag}
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* Sentiment Timeline */}
          <section>
            <SectionLabel>Sentiment History</SectionLabel>
            {statsLoading ? (
              <SentimentTimelineSkeleton />
            ) : reviewStats && reviewStats.timeline.length >= 3 ? (
              <SentimentTimeline timeline={reviewStats.timeline} />
            ) : null}
          </section>

          {/* Playtime Chart */}
          <section>
            <SectionLabel>Playtime Sentiment</SectionLabel>
            {statsLoading ? (
              <PlaytimeChartSkeleton />
            ) : reviewStats ? (
              <PlaytimeChart
                buckets={reviewStats.playtime_buckets}
                insight={computePlaytimeInsight(reviewStats.playtime_buckets)}
                isPro={isPro}
              />
            ) : null}
          </section>

          {/* Analysis status */}
          <section className="text-center py-8">
            <div
              className="inline-flex items-center gap-3 px-6 py-4 rounded-xl"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <Clock className="w-5 h-5 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Analysis in progress — check back once this game reaches sufficient reviews.
              </p>
            </div>
          </section>

          {/* Steam link */}
          <section className="pt-8 border-t border-border">
            <a
              href={`https://store.steampowered.com/app/${appid}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              View on Steam Store &rarr;
            </a>
          </section>
        </div>
      </div>
    );
  }

  // Analyzed game state - full report
  return (
    <div className="min-h-screen bg-background">
      {/* Hero */}
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

        {/* Title block */}
        <div className="absolute bottom-0 left-0 right-0 px-6 pb-8 max-w-4xl">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {genres?.map((g) => (
              <Link
                key={g}
                href={`/genre/${slugify(g)}`}
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
            {name}
          </h1>
          <div className="flex flex-wrap items-center gap-3">
            <HiddenGemBadge score={report.hidden_gem_score ?? 0} />
            <span
              className="inline-block px-3 py-1 rounded-full text-xs font-mono uppercase tracking-widest"
              style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.1)",
              }}
            >
              {report.overall_sentiment ?? "\u2014"}
            </span>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="max-w-4xl mx-auto px-6 py-12 space-y-16">
        <Breadcrumbs items={breadcrumbItems} />

        {/* Section 1 - The Verdict */}
        <section className="animate-fade-up stagger-1">
          <SectionLabel>The Verdict</SectionLabel>
          <blockquote
            className="font-serif text-2xl md:text-3xl text-foreground/90 leading-snug mb-8 italic"
            style={{ letterSpacing: "-0.01em" }}
          >
            &ldquo;{report.one_liner ?? "Analysis loading\u2026"}&rdquo;
          </blockquote>
          <ScoreBar score={report.sentiment_score ?? 0} />
          <p className="mt-2 text-xs text-muted-foreground font-mono" data-testid="score-context">
            {scoreContextSentence(report.sentiment_score ?? 0)}
          </p>
        </section>

        {/* Section 2 - Quick Stats */}
        <section className="animate-fade-up stagger-2">
          <SectionLabel>Quick Stats</SectionLabel>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <BarChart3 className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Reviews</span>
              </div>
              <p className="font-mono text-sm font-medium truncate">{report.total_reviews_analyzed?.toLocaleString() ?? "—"}</p>
            </div>
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Calendar className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Released</span>
              </div>
              {releaseDate ? (
                <Link href={`/search?year_from=${new Date(releaseDate).getFullYear()}&year_to=${new Date(releaseDate).getFullYear()}`} className="font-mono text-sm font-medium hover:underline" style={{ color: "var(--teal)" }}>
                  {new Date(releaseDate).getFullYear()}
                </Link>
              ) : <p className="font-mono text-sm font-medium">—</p>}
            </div>
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <DollarSign className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Price</span>
              </div>
              <p className="font-mono text-sm font-medium truncate">{price}</p>
            </div>
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Star className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Developer</span>
              </div>
              {developer ? (
                <Link href={`/developer/${slugify(developer)}`} className="font-mono text-sm font-medium hover:underline truncate block" style={{ color: "var(--teal)" }}>
                  {developer}
                </Link>
              ) : <p className="font-mono text-sm font-medium">—</p>}
            </div>
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Clock className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Analyzed</span>
              </div>
              <p className="font-mono text-sm font-medium truncate">{report.last_analyzed ? new Date(report.last_analyzed).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"}</p>
            </div>
            {/* Review Velocity card */}
            <div className="p-4 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Zap className="w-4 h-4" />
                <span className="text-[10px] uppercase tracking-widest font-mono">Velocity</span>
              </div>
              {statsLoading ? (
                <div className="h-4 bg-secondary rounded animate-pulse w-20" />
              ) : reviewStats ? (
                <>
                  <p className="font-mono text-sm font-medium">
                    {reviewStats.review_velocity.reviews_per_day}/day
                  </p>
                  {(() => {
                    const m = momentumLabel(
                      reviewStats.review_velocity.reviews_last_30_days,
                      reviewStats.review_velocity.reviews_per_day
                    );
                    return (
                      <p className="text-[10px] font-mono mt-1" style={{ color: m.color }}>
                        {m.label}
                      </p>
                    );
                  })()}
                </>
              ) : (
                <p className="font-mono text-sm font-medium">—</p>
              )}
            </div>
          </div>
        </section>

        {/* Section 3 - Design Strengths */}
        <section className="animate-fade-up stagger-3">
          <SectionLabel>Design Strengths</SectionLabel>
          <ul className="space-y-3">
            {(report.design_strengths ?? []).map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "var(--positive)" }} />
                <span className="text-sm text-foreground/80 leading-relaxed">{item}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Section 4 - Gameplay Friction */}
        <section className="animate-fade-up stagger-4">
          <SectionLabel>Gameplay Friction</SectionLabel>
          <ul className="space-y-3">
            {(report.gameplay_friction ?? []).map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "var(--negative)" }} />
                <span className="text-sm text-foreground/80 leading-relaxed">{item}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Section 5 - Audience Profile */}
        {report.audience_profile && (
          <section className="animate-fade-up stagger-5">
            <SectionLabel>Audience Profile</SectionLabel>
            <div className="grid md:grid-cols-2 gap-6">
              <div className="p-5 rounded-xl space-y-4" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-1">Ideal Player</p>
                  <p className="text-sm text-foreground/80">{report.audience_profile.ideal_player}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-1">Casual Friendliness</p>
                  <p className="text-sm text-foreground/80">{report.audience_profile.casual_friendliness}</p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-2">Player Archetypes</p>
                  <div className="flex flex-wrap gap-2">
                    {report.audience_profile.archetypes?.map((a) => (
                      <span key={a} className="text-xs px-2.5 py-1 rounded-full font-mono" style={{ background: "rgba(45,185,212,0.08)", border: "1px solid rgba(45,185,212,0.2)", color: "var(--teal)" }}>
                        {a}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest font-mono text-muted-foreground mb-2">Not For</p>
                  <div className="flex flex-wrap gap-2">
                    {report.audience_profile.not_for?.map((n) => (
                      <span key={n} className="text-xs px-2.5 py-1 rounded-full font-mono" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)", color: "rgba(239,68,68,0.8)" }}>
                        {n}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Section 6 - Sentiment Trend */}
        {report.sentiment_trend && (
          <section className="animate-fade-up stagger-6">
            <SectionLabel>Sentiment Trend</SectionLabel>
            <div className="p-5 rounded-xl flex items-start gap-4" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
              <TrendIcon trend={report.sentiment_trend} />
              <div>
                <p className="text-sm font-mono font-medium mb-1">{report.sentiment_trend}</p>
                <p className="text-sm text-muted-foreground leading-relaxed">{report.sentiment_trend_note}</p>
              </div>
            </div>
          </section>
        )}

        {/* Section 7 - Genre Context */}
        {report.genre_context && (
          <section>
            <SectionLabel>Genre Context</SectionLabel>
            <p className="text-sm text-foreground/80 leading-relaxed">{report.genre_context}</p>
          </section>
        )}

        {/* Section 8 - Player Wishlist */}
        {report.player_wishlist && report.player_wishlist.length > 0 && (
          <section>
            <SectionLabel>Player Wishlist</SectionLabel>
            <ul className="space-y-3">
              {report.player_wishlist.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <Lightbulb className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "var(--gem)" }} />
                  <span className="text-sm text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Section 9 - Churn Triggers */}
        {report.churn_triggers && report.churn_triggers.length > 0 && (
          <section>
            <SectionLabel>Churn Triggers</SectionLabel>
            <ul className="space-y-3">
              {report.churn_triggers.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <DoorOpen className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "var(--negative)" }} />
                  <span className="text-sm text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Section 10 - Developer Priorities */}
        {report.dev_priorities && report.dev_priorities.length > 0 && (
          <section>
            <SectionLabel>Developer Priorities</SectionLabel>
            <div className="space-y-4">
              {report.dev_priorities.map((p, i) => (
                <div key={i} className="p-4 rounded-lg" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
                  <div className="flex items-start gap-3 mb-2">
                    <span className="font-mono text-xs px-1.5 py-0.5 rounded mt-0.5 flex-shrink-0" style={{ background: "rgba(45,185,212,0.1)", color: "var(--teal)" }}>
                      #{i + 1}
                    </span>
                    <p className="text-sm font-medium text-foreground flex items-center gap-2">
                      <Target className="w-3.5 h-3.5 flex-shrink-0" style={{ color: "var(--teal)" }} />
                      {p.action}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground ml-8 mb-3 leading-relaxed">{p.why_it_matters}</p>
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
            {/* Contextual Pro CTA */}
            {primaryGenre && (
              <p className="mt-6 text-xs text-muted-foreground">
                Researching the {primaryGenre} market? See what players want that no game currently delivers.{" "}
                <Link href="/pro" className="font-mono hover:text-foreground transition-colors" style={{ color: "var(--teal)" }}>
                  Genre Intelligence (Pro) &rarr;
                </Link>
              </p>
            )}
          </section>
        )}

        {/* Section 11 - Competitive Context */}
        {report.competitive_context && report.competitive_context.length > 0 && (
          <section>
            <SectionLabel>Competitive Context</SectionLabel>
            <div className="space-y-3">
              {report.competitive_context.map((c, i) => (
                <div key={i} className="p-4 rounded-xl flex items-start gap-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
                  <Swords className="w-4 h-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-mono font-medium text-foreground">{c.game}</span>
                      <span className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full" style={{ background: "rgba(255,255,255,0.05)", color: "var(--muted-foreground)" }}>
                        {c.comparison_sentiment}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">{c.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Sentiment Timeline */}
        <section>
          <SectionLabel>Sentiment History</SectionLabel>
          {statsLoading ? (
            <SentimentTimelineSkeleton />
          ) : reviewStats && reviewStats.timeline.length >= 3 ? (
            <SentimentTimeline timeline={reviewStats.timeline} />
          ) : null}
        </section>

        {/* Playtime Chart + insight */}
        <section>
          <SectionLabel>Playtime Sentiment</SectionLabel>
          {statsLoading ? (
            <PlaytimeChartSkeleton />
          ) : reviewStats ? (
            <PlaytimeChart
              buckets={reviewStats.playtime_buckets}
              insight={computePlaytimeInsight(reviewStats.playtime_buckets)}
              isPro={isPro}
            />
          ) : null}
        </section>

        {/* Competitive Benchmark (Pro — blurred for free users) */}
        {benchmarks && (
          <section>
            <SectionLabel>Competitive Benchmark</SectionLabel>
            <CompetitiveBenchmark
              benchmarks={benchmarks}
              genre={primaryGenre}
              year={releaseDate ? new Date(releaseDate).getFullYear() : undefined}
              isPro={isPro}
            />
          </section>
        )}

        {/* Section 12 - Tags */}
        {tags && tags.length > 0 && (
          <section>
            <SectionLabel>Tags</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <Link
                  key={tag}
                  href={`/tag/${slugify(tag)}`}
                  className="text-xs px-2.5 py-1 rounded-full font-mono transition-colors hover:text-foreground"
                  style={{
                    background: "rgba(45,185,212,0.08)",
                    border: "1px solid rgba(45,185,212,0.2)",
                    color: "var(--teal)",
                  }}
                >
                  {tag}
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Footer */}
        <section className="pt-8 border-t border-border">
          <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
            <Users className="w-3.5 h-3.5" />
            <span>
              Analysis based on {report.total_reviews_analyzed?.toLocaleString() ?? "\u2014"} reviews
            </span>
            {report.last_analyzed && (
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
          <div className="mt-4">
            <a
              href={`https://store.steampowered.com/app/${appid}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              View on Steam Store &rarr;
            </a>
          </div>
        </section>
      </div>
    </div>
  );
}
