"use client";

import Link from "next/link";
import { BarChart3, Users, TrendingUp, FileText } from "lucide-react";
import { MiniSentimentChart } from "./MiniSentimentChart";
import { MiniOverlapList } from "./MiniOverlapList";
import { MiniTrendLine } from "./MiniTrendLine";
import type { HomeIntelSnapshot } from "@/lib/types";

interface IntelligenceCardsProps {
  snapshot: HomeIntelSnapshot;
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

function EmptyState() {
  return (
    <p className="text-xs text-muted-foreground italic">
      Sample updates daily.
    </p>
  );
}

export function IntelligenceCards({ snapshot }: IntelligenceCardsProps) {
  const { sentiment_sample, overlap_sample, trend_sample, report_sample } =
    snapshot;

  const trendLine = (trend_sample?.periods ?? []).map((p) => ({
    period: p.period,
    value: p.positive_pct,
  }));

  return (
    <section>
      <h2 className="font-serif text-xl font-semibold mb-6">
        What You Get
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <IntelCard
          icon={<BarChart3 className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Player Sentiment"
          subtitle="Structured by playtime, timeline, and behavior"
          href="/search?sort=review_count"
        >
          {sentiment_sample && sentiment_sample.timeline.length >= 2 ? (
            <MiniSentimentChart timeline={sentiment_sample.timeline} />
          ) : (
            <EmptyState />
          )}
        </IntelCard>

        <IntelCard
          icon={<Users className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Competitive Intelligence"
          subtitle="Real audience overlap from reviewer behavior"
          href="/search?sort=review_count"
        >
          {overlap_sample && overlap_sample.overlaps.length > 0 ? (
            <MiniOverlapList overlaps={overlap_sample.overlaps} />
          ) : (
            <EmptyState />
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
            <EmptyState />
          )}
        </IntelCard>

        <IntelCard
          icon={<FileText className="w-4 h-4" style={{ color: "var(--teal)" }} />}
          title="Deep Review Reports"
          subtitle="Thousands of reviews distilled into structured intelligence"
          href="/reports"
        >
          {report_sample && report_sample.one_liner ? (
            <div className="space-y-2">
              <p className="text-xs text-foreground/80 italic line-clamp-2">
                &ldquo;{report_sample.one_liner}&rdquo;
              </p>
              {report_sample.design_strengths.slice(0, 2).map((s, i) => (
                <p key={`${s}-${i}`} className="text-xs text-muted-foreground line-clamp-1">
                  <span style={{ color: "var(--positive)" }}>+</span> {s}
                </p>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </IntelCard>
      </div>
    </section>
  );
}
