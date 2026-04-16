"use client";

import { useState, useEffect } from "react";
import { usePro } from "@/lib/pro";
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
  Clock,
} from "lucide-react";
import type { GameReport, ReviewStats, Benchmarks } from "@/lib/types";
import { getReviewStats, getBenchmarks } from "@/lib/api";
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
import { MarketReach } from "@/components/game/MarketReach";
import { PromiseGap } from "@/components/game/PromiseGap";
import { GameHero } from "@/components/game/GameHero";
import { SteamFactsCard } from "@/components/game/SteamFactsCard";
import { QuickStats } from "@/components/game/QuickStats";
import { GameAnalyticsSection } from "@/components/analytics/GameAnalyticsSection";
import { RequestAnalysis } from "@/components/game/RequestAnalysis";
import { parseLocalDate, slugify, relativeTime } from "@/lib/format";

interface GameReportClientProps {
  report: GameReport | null;
  appid: number;
  gameName?: string;
  headerImage?: string;
  releaseDate?: string;
  developer?: string;
  developerSlug?: string;
  publisher?: string;
  publisherSlug?: string;
  priceUsd?: number | null;
  isFree?: boolean;
  genres?: string[];
  tags?: string[];
  shortDesc?: string;
  reviewCount?: number;
  deckCompatibility?: number | null;
  deckTestResults?: Array<{ display_type: number; loc_token: string }>;
  isEarlyAccess?: boolean;
  // Steam-sourced sentiment + per-source freshness (data-source-clarity refactor).
  // The Steam Facts zone reads these directly from Steam — never from the LLM.
  positivePct?: number | null;
  reviewScoreDesc?: string | null;
  metaCrawledAt?: string | null;
  reviewCrawledAt?: string | null;
  reviewsCompletedAt?: string | null;
  tagsCrawledAt?: string | null;
  lastAnalyzed?: string | null;
  // Boxleiter v1 revenue estimate — surfaced by <MarketReach />
  estimatedOwners?: number | null;
  estimatedRevenueUsd?: number | null;
  revenueEstimateMethod?: string | null;
  revenueEstimateReason?: string | null;
  // positivePct / reviewScoreDesc / reviewCount above are pre-resolved by the
  // page to the phase-appropriate values (post-release for ex-EA games, all-time
  // otherwise). `isExEarlyAccess` is the definitive "has EA history AND released
  // AND no longer flagged EA" predicate — this is what gates the ex-EA banner
  // so active Early Access games don't get mislabelled.
  reviewPhase?: "post_release" | "early_access" | "all_time";
  hasEarlyAccessHistory?: boolean;
  isExEarlyAccess?: boolean;
}

function formatMonth(iso: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  return parseLocalDate(iso).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
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
  report,
  appid,
  gameName,
  headerImage,
  releaseDate,
  developer,
  developerSlug,
  publisher,
  publisherSlug,
  priceUsd,
  isFree,
  genres,
  tags,
  shortDesc,
  reviewCount,
  deckCompatibility,
  deckTestResults,
  isEarlyAccess,
  positivePct,
  reviewScoreDesc,
  metaCrawledAt,
  reviewCrawledAt,
  reviewsCompletedAt,
  lastAnalyzed,
  estimatedOwners,
  estimatedRevenueUsd,
  revenueEstimateMethod,
  revenueEstimateReason,
  reviewPhase,
  hasEarlyAccessHistory,
  isExEarlyAccess,
}: GameReportClientProps) {
  const isPro = usePro();
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

  return (
    <div className="min-h-screen bg-background">
      <GameHero
        name={name}
        headerImage={headerImage}
        genres={genres}
        isEarlyAccess={isEarlyAccess}
        deckCompatibility={deckCompatibility}
        deckTestResults={deckTestResults}
        hiddenGemScore={report?.hidden_gem_score ?? null}
        positivePct={positivePct ?? null}
        reviewScoreDesc={reviewScoreDesc ?? null}
        developer={developer}
        developerSlug={developerSlug}
        publisher={publisher}
        publisherSlug={publisherSlug}
      />
      {isExEarlyAccess && (
        <div
          data-testid="ex-ea-indicator"
          className="max-w-4xl mx-auto px-6 pt-4 -mb-6 text-xs font-mono uppercase tracking-widest text-muted-foreground"
        >
          {reviewPhase === "post_release"
            ? "ex-Early Access — showing post-release review numbers (matches Steam's store UI)"
            : "ex-Early Access — no post-release reviews yet; showing EA-era numbers"}
        </div>
      )}

      <div className="max-w-4xl mx-auto px-6 py-12 space-y-16">
        <Breadcrumbs items={breadcrumbItems} />

        {/* The Verdict (analyzed only) — LLM one-liner + Compare CTA +
            SteamPulse Analysis marker. Steam Facts lives inside this
            section on analyzed pages so it visually anchors the Verdict;
            unanalyzed pages still get Steam Facts below. */}
        {report && (
          <section className="animate-fade-up stagger-1">
            <SectionLabel>The Verdict</SectionLabel>
            <blockquote
              className="font-serif text-2xl md:text-3xl text-foreground/90 leading-snug mb-4 italic"
              style={{ letterSpacing: "-0.01em" }}
            >
              &ldquo;{report.one_liner ?? "Analysis loading\u2026"}&rdquo;
            </blockquote>
            <div className="mb-8">
              <Link
                href={`/compare?appids=${appid}`}
                data-testid="game-compare-deeplink"
                className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full border"
                style={{ borderColor: "var(--teal)", color: "var(--teal)" }}
              >
                <Swords className="w-3.5 h-3.5" />
                Compare with…
              </Link>
            </div>
            <div className="mb-4">
              <SteamFactsCard
                positivePct={positivePct ?? null}
                reviewScoreDesc={reviewScoreDesc ?? null}
                reviewCrawledAt={reviewCrawledAt}
                reviewsCompletedAt={reviewsCompletedAt}
                metaCrawledAt={metaCrawledAt}
              />
            </div>
            <div className="flex items-center justify-between text-xs font-mono uppercase tracking-widest text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden>✨</span>
                SteamPulse Analysis
              </span>
              <span className="flex items-center gap-3">
                {report.total_reviews_analyzed != null && (
                  <span>{report.total_reviews_analyzed.toLocaleString()} reviews</span>
                )}
                {(() => {
                  const ts = relativeTime(lastAnalyzed);
                  return ts ? <span>Analyzed {ts}</span> : null;
                })()}
              </span>
            </div>
          </section>
        )}

        {/* Standalone Steam Facts — unanalyzed pages don't have a Verdict
            block, but Steam sentiment is Steam-owned and independent of
            any LLM pass, so we surface it here. */}
        {!report && (
          <section className="animate-fade-up stagger-1">
            <SectionLabel>Steam Facts</SectionLabel>
            <SteamFactsCard
              positivePct={positivePct ?? null}
              reviewScoreDesc={reviewScoreDesc ?? null}
              reviewCrawledAt={reviewCrawledAt}
              reviewsCompletedAt={reviewsCompletedAt}
              metaCrawledAt={metaCrawledAt}
            />
          </section>
        )}

        <QuickStats
          reviewCount={reviewCount ?? null}
          totalReviewsAnalyzed={report?.total_reviews_analyzed ?? null}
          releaseDate={releaseDate}
          price={price}
          lastAnalyzed={report?.last_analyzed ?? lastAnalyzed ?? null}
          reviewStats={reviewStats}
          statsLoading={statsLoading}
          reviewCrawledAt={reviewCrawledAt}
          reviewsCompletedAt={reviewsCompletedAt}
          metaCrawledAt={metaCrawledAt}
        />

        {/* Market Reach — Boxleiter v1 revenue estimate. Independent of the
            LLM pass (review count + price + genre/tags is enough), so it
            renders on unanalyzed pages too. Pro-gated.
            TODO(pro-gating): `isPro` comes from usePro() context; free tier
            is the current default until auth + subscription wiring lands. */}
        <MarketReach
          estimatedOwners={estimatedOwners ?? null}
          estimatedRevenueUsd={estimatedRevenueUsd ?? null}
          method={revenueEstimateMethod ?? null}
          reason={revenueEstimateReason ?? null}
          reviewCount={reviewCount ?? 0}
          isPro={isPro}
        />

        {/* About — only shown on unanalyzed pages. On analyzed pages the
            LLM one-liner + narrative sections carry this weight. */}
        {!report && shortDesc && (
          <section>
            <SectionLabel>About</SectionLabel>
            <p className="text-base text-foreground/80 leading-relaxed">{shortDesc}</p>
          </section>
        )}

        {/* --- Report-only narrative sections --- */}

        {report && (
          <section className="animate-fade-up stagger-3">
            <SectionLabel>Design Strengths</SectionLabel>
            <ul className="space-y-3">
              {(report.design_strengths ?? []).map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <CheckCircle2
                    className="w-4 h-4 mt-0.5 flex-shrink-0"
                    style={{ color: "var(--positive)" }}
                  />
                  <span className="text-base text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {report && (
          <section className="animate-fade-up stagger-4">
            <SectionLabel>Gameplay Friction</SectionLabel>
            <ul className="space-y-3">
              {(report.gameplay_friction ?? []).map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <AlertCircle
                    className="w-4 h-4 mt-0.5 flex-shrink-0"
                    style={{ color: "var(--negative)" }}
                  />
                  <span className="text-base text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {report?.audience_profile && (
          <section className="animate-fade-up stagger-5">
            <SectionLabel>Audience Profile</SectionLabel>
            <div className="grid md:grid-cols-2 gap-6">
              <div
                className="p-5 rounded-xl space-y-4"
                style={{ background: "var(--card)", border: "1px solid var(--border)" }}
              >
                <div>
                  <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-1">
                    Ideal Player
                  </p>
                  <p className="text-base text-foreground/80">
                    {report.audience_profile.ideal_player}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-1">
                    Casual Friendliness
                  </p>
                  <p className="text-base text-foreground/80">
                    {report.audience_profile.casual_friendliness}
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">
                    Player Archetypes
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {report.audience_profile.archetypes?.map((a) => (
                      <span
                        key={a}
                        className="text-sm px-3 py-1.5 rounded-full font-mono"
                        style={{
                          background: "rgba(45,185,212,0.08)",
                          border: "1px solid rgba(45,185,212,0.2)",
                          color: "var(--teal)",
                        }}
                      >
                        {a}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">
                    Not For
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {report.audience_profile.not_for?.map((n) => (
                      <span
                        key={n}
                        className="text-sm px-3 py-1.5 rounded-full font-mono"
                        style={{
                          background: "rgba(239,68,68,0.08)",
                          border: "1px solid rgba(239,68,68,0.15)",
                          color: "rgba(239,68,68,0.8)",
                        }}
                      >
                        {n}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {report?.sentiment_trend && (
          <section className="animate-fade-up stagger-6">
            <SectionLabel>Sentiment Trend</SectionLabel>
            <div
              className="p-5 rounded-xl flex items-start gap-4"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <TrendIcon trend={report.sentiment_trend} />
              <div>
                <p className="text-base font-mono font-medium mb-1">{report.sentiment_trend}</p>
                <p className="text-base text-muted-foreground leading-relaxed">
                  {report.sentiment_trend_note}
                </p>
              </div>
            </div>
          </section>
        )}

        {report?.genre_context && (
          <section>
            <SectionLabel>Genre Context</SectionLabel>
            <p className="text-base text-foreground/80 leading-relaxed">
              {report.genre_context}
            </p>
          </section>
        )}

        {report?.store_page_alignment && (
          <section>
            <SectionLabel>Promise Gap</SectionLabel>
            <PromiseGap alignment={report.store_page_alignment} isPro={isPro} />
          </section>
        )}

        {report?.player_wishlist && report.player_wishlist.length > 0 && (
          <section>
            <SectionLabel>Player Wishlist</SectionLabel>
            <ul className="space-y-3">
              {report.player_wishlist.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <Lightbulb
                    className="w-4 h-4 mt-0.5 flex-shrink-0"
                    style={{ color: "var(--gem)" }}
                  />
                  <span className="text-base text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {report?.churn_triggers && report.churn_triggers.length > 0 && (
          <section>
            <SectionLabel>Churn Triggers</SectionLabel>
            <ul className="space-y-3">
              {report.churn_triggers.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <DoorOpen
                    className="w-4 h-4 mt-0.5 flex-shrink-0"
                    style={{ color: "var(--negative)" }}
                  />
                  <span className="text-base text-foreground/80 leading-relaxed">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {report?.dev_priorities && report.dev_priorities.length > 0 && (
          <section>
            <SectionLabel>Developer Priorities</SectionLabel>
            <div className="space-y-4">
              {report.dev_priorities.map((p, i) => (
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
                      style={{ background: "rgba(45,185,212,0.1)", color: "var(--teal)" }}
                    >
                      #{i + 1}
                    </span>
                    <p className="text-base font-medium text-foreground flex items-center gap-2">
                      <Target
                        className="w-3.5 h-3.5 flex-shrink-0"
                        style={{ color: "var(--teal)" }}
                      />
                      {p.action}
                    </p>
                  </div>
                  <p className="text-sm text-muted-foreground ml-8 mb-3 leading-relaxed">
                    {p.why_it_matters}
                  </p>
                  <div className="flex gap-4 ml-8">
                    <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
                      Freq: <span className="text-foreground/60">{p.frequency}</span>
                    </span>
                    <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
                      Effort: <span className="text-foreground/60">{p.effort}</span>
                    </span>
                  </div>
                </div>
              ))}
            </div>
            {primaryGenre && (
              <p className="mt-6 text-sm text-muted-foreground">
                Researching the {primaryGenre} market? See what players want that no game
                currently delivers.{" "}
                <Link
                  href="/pro"
                  className="font-mono hover:text-foreground transition-colors"
                  style={{ color: "var(--teal)" }}
                >
                  Genre Intelligence (Pro) &rarr;
                </Link>
              </p>
            )}
          </section>
        )}

        {report?.competitive_context && report.competitive_context.length > 0 && (
          <section>
            <SectionLabel>Competitive Context</SectionLabel>
            <div className="space-y-3">
              {report.competitive_context.map((c, i) => (
                <div
                  key={i}
                  className="p-4 rounded-xl flex items-start gap-4"
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <Swords className="w-4 h-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-base font-mono font-medium text-foreground">
                        {c.game}
                      </span>
                      <span
                        className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded-full"
                        style={{
                          background: "rgba(255,255,255,0.05)",
                          color: "var(--muted-foreground)",
                        }}
                      >
                        {c.comparison_sentiment}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed">{c.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* --- Steam-sourced charts — rendered on both paths --- */}

        <section>
          <SectionLabel>Sentiment History</SectionLabel>
          {statsLoading ? (
            <SentimentTimelineSkeleton />
          ) : reviewStats && reviewStats.timeline.length >= 2 ? (
            <SentimentTimeline timeline={reviewStats.timeline} />
          ) : null}
        </section>

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

        {report && benchmarks && (
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

        {tags && tags.length > 0 && (
          <section>
            <SectionLabel>Tags</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <Link
                  key={tag}
                  href={`/tag/${slugify(tag)}`}
                  className="text-sm px-3 py-1.5 rounded-full font-mono transition-colors hover:text-foreground"
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

        {report && <GameAnalyticsSection appid={appid} gameName={name} />}

        {!report && (
          <section className="text-center py-8">
            <div
              className="flex flex-col items-center gap-4 px-6 py-6 rounded-xl"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-muted-foreground" />
                <p className="text-base text-muted-foreground">
                  This game hasn&apos;t been analyzed yet.
                </p>
              </div>
              <RequestAnalysis appid={appid} />
            </div>
          </section>
        )}

        {/* Footer: analyzed games get the "Analysis based on N reviews" line;
            both show the Steam store link. */}
        <section className="pt-8 border-t border-border">
          {report && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground font-mono">
              <Users className="w-3.5 h-3.5" />
              <span>
                Analysis based on{" "}
                {report.total_reviews_analyzed?.toLocaleString() ?? "\u2014"} reviews
                {(() => {
                  if (!report.review_date_range_start || !report.review_date_range_end) return null;
                  const startMonth = formatMonth(report.review_date_range_start);
                  const endMonth = formatMonth(report.review_date_range_end);
                  if (!startMonth || !endMonth) return null;
                  return (
                    <span>
                      {" "}({startMonth === endMonth ? startMonth : `${startMonth} \u2013 ${endMonth}`})
                    </span>
                  );
                })()}
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
          )}
          <div className={report ? "mt-4" : ""}>
            <a
              href={`https://store.steampowered.com/app/${appid}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              View on Steam Store &rarr;
            </a>
          </div>
        </section>
      </div>
    </div>
  );
}
