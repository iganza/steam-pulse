"use client";

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
} from "lucide-react";
import type { GameReport, ReviewStats, Benchmarks, RelatedAnalyzedGame } from "@/lib/types";
import { SectionLabel } from "@/components/game/SectionLabel";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import {
  SentimentTimeline,
  SentimentTimelineStub,
} from "@/components/game/SentimentTimeline";
import {
  PlaytimeChart,
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
import { RelatedAnalyzedGames } from "@/components/game/RelatedAnalyzedGames";
import { parseLocalDate, slugify, relativeTime } from "@/lib/format";
import { AuthorByline } from "@/components/shared/AuthorByline";
import { AUTHOR_NAME, METHODOLOGY_PATH } from "@/lib/author";

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
  reviewCountEnglish?: number | null;
  reviewCountAllLanguages?: number | null;
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
  // Boxleiter v2 revenue estimate — surfaced by <MarketReach />
  estimatedOwners?: number | null;
  estimatedRevenueUsd?: number | null;
  revenueEstimateMethod?: string | null;
  revenueEstimateReason?: string | null;
  /** Pre-fetched neighbors for the "More games like this" section on
   *  un-analyzed pages. Empty on analyzed pages. */
  relatedAnalyzed?: RelatedAnalyzedGame[];
  reviewStats: ReviewStats | null;
  benchmarks: Benchmarks | null;
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
  reviewCountEnglish,
  reviewCountAllLanguages,
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
  relatedAnalyzed = [],
  reviewStats,
  benchmarks,
}: GameReportClientProps) {
  const name = report?.game_name ?? gameName ?? "Game Report";
  const price = isFree ? "Free" : priceUsd ? `$${priceUsd.toFixed(2)}` : "\u2014";
  const primaryGenre = genres?.[0];

  // Hoist the Steam-chart render gates so the JSX below stays readable.
  // PlaytimeChart's own internal guard is `total < 50`; we mirror it here
  // so the parent <section> (including its SectionLabel) doesn't mount an
  // empty shell when the chart would render null.
  const playtimeReviewTotal =
    reviewStats?.playtime_buckets.reduce((s, b) => s + b.reviews, 0) ?? 0;
  const showSentimentHistory =
    !!reviewStats && reviewStats.timeline.length >= 3;
  // Un-analyzed pages keep the Sentiment History header visible with an
  // informative stub so returning visitors see the section populate over time.
  const showSentimentHistoryStub =
    !report && !!reviewStats && reviewStats.timeline.length < 3;
  const showPlaytimeSentiment = !!reviewStats && playtimeReviewTotal >= 50;

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
              className="font-serif text-2xl md:text-3xl text-foreground/90 leading-snug mb-8 italic"
              style={{ letterSpacing: "-0.01em" }}
            >
              &ldquo;{report.one_liner ?? "Analysis loading\u2026"}&rdquo;
            </blockquote>
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
            <AuthorByline className="mt-3 text-xs font-mono uppercase tracking-widest text-muted-foreground" />
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
          reviewCountEnglish={reviewCountEnglish ?? null}
          reviewCountAllLanguages={reviewCountAllLanguages ?? null}
          totalReviewsAnalyzed={report?.total_reviews_analyzed ?? null}
          releaseDate={releaseDate}
          price={price}
          lastAnalyzed={report?.last_analyzed ?? lastAnalyzed ?? null}
          reviewStats={reviewStats}
          statsLoading={false}
          reviewCrawledAt={reviewCrawledAt}
          reviewsCompletedAt={reviewsCompletedAt}
          metaCrawledAt={metaCrawledAt}
        />

        {/* Market Reach — Boxleiter v2 revenue estimate. Independent of the
            LLM pass (review count + price + genre/tags is enough), so it
            renders on unanalyzed pages too. */}
        <MarketReach
          estimatedOwners={estimatedOwners ?? null}
          estimatedRevenueUsd={estimatedRevenueUsd ?? null}
          method={revenueEstimateMethod ?? null}
          reason={revenueEstimateReason ?? null}
          reviewCount={reviewCountAllLanguages ?? reviewCount ?? 0}
          reviewCountEnglish={reviewCountEnglish ?? null}
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
            <PromiseGap alignment={report.store_page_alignment} />
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

        {/* --- Steam-sourced charts — rendered on both paths when data is
            sufficient. Playtime Sentiment and Competitive Benchmark hide
            entirely below their thresholds. Sentiment History is special on
            un-analyzed pages: when the timeline has < 3 points we keep the
            header and render an informative stub so returning visitors watch
            the chart populate over time. Analyzed pages still hide the
            section below the threshold. --- */}

        {showSentimentHistory ? (
          <section>
            <SectionLabel>Sentiment History</SectionLabel>
            <SentimentTimeline timeline={reviewStats!.timeline} />
          </section>
        ) : showSentimentHistoryStub ? (
          <section>
            <SectionLabel>Sentiment History</SectionLabel>
            <SentimentTimelineStub
              firstCrawlIso={
                reviewStats?.timeline?.[0]?.week
                ?? reviewCrawledAt
                ?? reviewsCompletedAt
              }
            />
          </section>
        ) : null}

        {showPlaytimeSentiment ? (
          <section>
            <SectionLabel>Playtime Sentiment</SectionLabel>
            <PlaytimeChart
              buckets={reviewStats!.playtime_buckets}
              insight={computePlaytimeInsight(reviewStats!.playtime_buckets)}
            />
          </section>
        ) : null}

        {benchmarks && benchmarks.cohort_size >= 10 && (
          <section>
            <SectionLabel>Competitive Benchmark</SectionLabel>
            <CompetitiveBenchmark
              benchmarks={benchmarks}
              genre={primaryGenre}
              year={releaseDate ? new Date(releaseDate).getFullYear() : undefined}
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

        {/* Deep Dive Analytics — ungated from report. The section renders
            overlap, top reviews, review velocity, playtime sentiment, and EA
            impact from Steam-sourced endpoints that don't depend on the LLM
            pass. Self-hides when all five endpoints return empty. */}
        <GameAnalyticsSection appid={appid} gameName={name} />



        {!report && <RequestAnalysis appid={appid} gameTitle={name} />}

        {!report && relatedAnalyzed.length > 0 && (
          <RelatedAnalyzedGames games={relatedAnalyzed} />
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
          {report && (
            <p
              className="mt-4 text-sm text-muted-foreground leading-relaxed italic"
              data-testid="methodology-footer"
            >
              This page was synthesised by the SteamPulse three-phase pipeline
              {report.total_reviews_analyzed != null ? (
                <>
                  {" "}({report.total_reviews_analyzed.toLocaleString()} reviews
                  analysed across chunk → merge → synthesise phases)
                </>
              ) : null}
              , reviewed and curated by {AUTHOR_NAME}. See the{" "}
              <Link
                href={METHODOLOGY_PATH}
                className="underline underline-offset-2 hover:text-foreground transition-colors"
              >
                methodology
              </Link>{" "}
              for the full pipeline and quote-traceability rules.
            </p>
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
