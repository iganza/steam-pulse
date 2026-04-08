"use client";

import Link from "next/link";
import { SectionLabel } from "@/components/game/SectionLabel";

interface MarketReachProps {
  estimatedOwners: number | null;
  estimatedRevenueUsd: number | null;
  method: string | null;
  // "insufficient_reviews" | "free_to_play" | "missing_price" | "excluded_type" | null
  reason: string | null;
  reviewCount: number;
  isPro: boolean;
}

// ±50% confidence band — matches the documented Boxleiter v1 precision.
// Range is computed in the frontend so the backend can keep a single point
// estimate in the `games` row.
const CONFIDENCE = 0.5;

/** Round to 2 significant figures so the displayed range reads as honest
 * ("180k – 540k") rather than fake-precise ("182,194 – 546,582"). */
function roundToSigFigs(value: number, sigFigs = 2): number {
  if (value === 0 || !Number.isFinite(value)) return value;
  const magnitude = Math.pow(10, sigFigs - Math.ceil(Math.log10(Math.abs(value))));
  return Math.round(value * magnitude) / magnitude;
}

const OWNER_COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const OWNER_FULL = new Intl.NumberFormat("en-US");

function formatOwners(n: number): string {
  return n >= 100_000 ? OWNER_COMPACT.format(n) : OWNER_FULL.format(n);
}

const REVENUE_FMT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

function formatRevenue(n: number): string {
  return REVENUE_FMT.format(n);
}

function emptyStateCopy(reason: string | null, reviewCount: number): string {
  switch (reason) {
    case "insufficient_reviews":
      return `Not enough reviews yet to estimate (${reviewCount}/50).`;
    case "free_to_play":
      return "Free-to-play — revenue estimates don't apply.";
    case "missing_price":
      return "No estimate: missing store price.";
    case "excluded_type":
      return "No estimate: DLC, demos, and tools aren't eligible.";
    default:
      return "No estimate available.";
  }
}

function ConfidencePill() {
  return (
    <span
      className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
      style={{
        background: "rgba(255,255,255,0.06)",
        color: "var(--muted-foreground)",
        border: "1px solid var(--border)",
      }}
    >
      ±50%
    </span>
  );
}

function MethodPill({ method }: { method: string }) {
  return (
    <Link
      href="/methodology/revenue"
      className="inline-flex items-center text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded-full hover:underline"
      style={{
        background: "rgba(45,185,212,0.1)",
        color: "var(--teal)",
        border: "1px solid rgba(45,185,212,0.25)",
      }}
      title="How is this calculated?"
    >
      {method}
    </Link>
  );
}

function Stat({
  label,
  low,
  high,
  formatter,
}: {
  label: string;
  low: number;
  high: number;
  formatter: (n: number) => string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
          {label}
        </span>
        <ConfidencePill />
      </div>
      <p className="font-mono text-lg font-medium">
        {formatter(low)} <span className="text-muted-foreground">–</span> {formatter(high)}
      </p>
    </div>
  );
}

export function MarketReach({
  estimatedOwners,
  estimatedRevenueUsd,
  method,
  reason,
  reviewCount,
  isPro,
}: MarketReachProps) {
  const hasEstimate = estimatedOwners != null && estimatedRevenueUsd != null;

  return (
    <section className="animate-fade-up" data-testid="market-reach">
      <SectionLabel>Market Reach</SectionLabel>
      <div
        className="p-4 rounded-xl relative"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        {!hasEstimate ? (
          <p
            className="text-sm font-mono text-muted-foreground"
            data-testid="market-reach-empty"
          >
            {emptyStateCopy(reason, reviewCount)}
          </p>
        ) : (
          <>
            <div
              className={
                isPro
                  ? "grid gap-5 md:grid-cols-2"
                  : "grid gap-5 md:grid-cols-2 blur-sm pointer-events-none select-none"
              }
              aria-hidden={!isPro}
            >
              <Stat
                label="Estimated owners"
                low={roundToSigFigs(estimatedOwners! * (1 - CONFIDENCE))}
                high={roundToSigFigs(estimatedOwners! * (1 + CONFIDENCE))}
                formatter={formatOwners}
              />
              <Stat
                label="Estimated gross revenue"
                low={roundToSigFigs(estimatedRevenueUsd! * (1 - CONFIDENCE))}
                high={roundToSigFigs(estimatedRevenueUsd! * (1 + CONFIDENCE))}
                formatter={formatRevenue}
              />
            </div>
            <div className="mt-4 flex items-center gap-3 flex-wrap">
              {method && <MethodPill method={method} />}
              <p className="text-xs text-muted-foreground leading-relaxed">
                Based on review count × genre/age/price-adjusted Boxleiter ratio.
                Gross revenue before Steam&rsquo;s 30% cut, refunds, and regional pricing.
              </p>
            </div>
            {!isPro && (
              <div
                className="absolute inset-0 flex flex-col items-center justify-center gap-2"
                aria-label="Market reach estimate — unlock with Pro"
              >
                <p className="text-sm font-mono text-foreground font-medium">
                  Market Reach
                </p>
                <Link
                  href="/pro"
                  data-testid="market-reach-cta"
                  className="text-sm font-mono px-4 py-1.5 rounded-full transition-colors"
                  style={{
                    background: "rgba(45,185,212,0.15)",
                    color: "var(--teal)",
                    border: "1px solid rgba(45,185,212,0.3)",
                  }}
                >
                  Unlock with Pro →
                </Link>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
