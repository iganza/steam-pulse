"use client";

import Link from "next/link";
import { BarChart3, Users, TrendingUp, FileText } from "lucide-react";
import { MiniSentimentChart } from "./MiniSentimentChart";
import { MiniOverlapList } from "./MiniOverlapList";
import { MiniTrendLine } from "./MiniTrendLine";
import type { HomeIntelSnapshot } from "@/lib/api";

interface IntelligenceCardsProps {
  snapshot: HomeIntelSnapshot | null;
}

function IntelCard({
  icon,
  title,
  subtitle,
  href,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="group block rounded-xl p-5 transition-all duration-200 hover:scale-[1.02]"
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <p className="text-xs text-muted-foreground mb-4">{subtitle}</p>
      <div className="min-h-[80px]">{children}</div>
    </Link>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[80px] items-center justify-center">
      <p className="text-xs font-mono text-muted-foreground/70">{label}</p>
    </div>
  );
}

export function IntelligenceCards({ snapshot }: IntelligenceCardsProps) {
  const sentiment = snapshot?.sentiment_sample;
  const overlap = snapshot?.overlap_sample;
  const trend = snapshot?.trend_sample;
  const reportSample = snapshot?.report_sample;

  const trendLine = (trend?.periods ?? []).map((p) => ({
    period: p.period,
    value: p.positive_pct,
  }));

  return (
    <section>
      <h2 className="font-serif text-xl font-semibold mb-6">What You Get</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <IntelCard
          icon={<BarChart3 className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Player Sentiment"
          subtitle="Structured by playtime, timeline, and behavior"
          href="/search?sort=review_count"
        >
          {sentiment && sentiment.timeline.length >= 2 ? (
            <MiniSentimentChart timeline={sentiment.timeline} />
          ) : (
            <EmptyState label="Sample updates daily" />
          )}
        </IntelCard>

        <IntelCard
          icon={<Users className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Competitive Intelligence"
          subtitle="Real audience overlap from reviewer behavior"
          href="/search?sort=review_count"
        >
          {overlap && overlap.overlaps.length > 0 ? (
            <MiniOverlapList overlaps={overlap.overlaps} />
          ) : (
            <EmptyState label="Sample updates daily" />
          )}
        </IntelCard>

        <IntelCard
          icon={<TrendingUp className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Market Intelligence"
          subtitle="Genre trends, pricing, release timing"
          href="/reports"
        >
          {trendLine.length >= 2 ? (
            <MiniTrendLine data={trendLine} />
          ) : (
            <EmptyState label="Sample updates daily" />
          )}
        </IntelCard>

        <IntelCard
          icon={<FileText className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Deep Review Reports"
          subtitle="Thousands of reviews distilled into structured intelligence"
          href="/reports"
        >
          {reportSample ? (
            <div className="space-y-2">
              <p className="text-xs text-foreground/80 italic line-clamp-2">
                &ldquo;{reportSample.report.one_liner}&rdquo;
              </p>
              {reportSample.report.design_strengths.slice(0, 2).map((s, i) => (
                <p
                  key={`${s}-${i}`}
                  className="text-xs text-muted-foreground line-clamp-1"
                >
                  <span style={{ color: "var(--positive)" }}>+</span> {s}
                </p>
              ))}
            </div>
          ) : (
            <EmptyState label="Sample updates daily" />
          )}
        </IntelCard>
      </div>
    </section>
  );
}
