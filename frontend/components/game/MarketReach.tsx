"use client";

import Link from "next/link";
import { SectionLabel } from "@/components/game/SectionLabel";

interface MarketReachProps {
  estimatedOwners: number | null;
  estimatedRevenueUsd: number | null;
  method: string | null;
  // "insufficient_reviews" | "free_to_play" | "missing_price" | "excluded_type" | null
  reason: string | null;
  // All-language review count — what the estimator actually consumed.
  reviewCount: number;
  // English-only count, used to decide whether to surface the "all languages"
  // basis line (only when it diverges from the all-language total).
  reviewCountEnglish: number | null;
}

// Confidence band widens in the small-sample zone where calibration data is thin.
function confidenceFor(reviewCount: number): number {
  if (reviewCount >= 50_000) return 0.4;
  if (reviewCount >= 5_000) return 0.6;
  return 1.0;
}

/** Round to 2 significant figures so the displayed value reads as honest
 * ("480M") rather than fake-precise ("483,127,914"). */
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
      return `Not enough reviews yet to estimate (${reviewCount.toLocaleString()}/500).`;
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

function ConfidencePill({ confidence }: { confidence: number }) {
  return (
    <span
      className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
      style={{
        background: "rgba(255,255,255,0.06)",
        color: "var(--muted-foreground)",
        border: "1px solid var(--border)",
      }}
    >
      ±{Math.round(confidence * 100)}%
    </span>
  );
}

function SmallSamplePill() {
  return (
    <span
      className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
      style={{
        background: "rgba(255,255,255,0.04)",
        color: "var(--muted-foreground)",
        border: "1px dashed var(--border)",
      }}
      title="Calibration data is thin below 5,000 reviews — treat as a rough directional read."
    >
      Small-sample
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
  value,
  formatter,
  confidence,
  showSmallSample,
}: {
  label: string;
  value: number;
  formatter: (n: number) => string;
  confidence: number;
  showSmallSample: boolean;
}) {
  const point = roundToSigFigs(value);
  const low = roundToSigFigs(value * (1 - confidence));
  const high = roundToSigFigs(value * (1 + confidence));
  const pctLabel = `±${Math.round(confidence * 100)}%`;
  const rangeTooltip = `Range: ${formatter(low)} – ${formatter(high)} (${pctLabel})`;

  return (
    <div>
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <span className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
          {label}
        </span>
        <ConfidencePill confidence={confidence} />
        {showSmallSample && <SmallSamplePill />}
      </div>
      <p className="font-mono text-lg font-medium" title={rangeTooltip}>
        <span className="text-muted-foreground mr-0.5">≈</span>
        {formatter(point)}
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
  reviewCountEnglish,
}: MarketReachProps) {
  const hasEstimate = estimatedOwners != null && estimatedRevenueUsd != null;
  const confidence = confidenceFor(reviewCount);
  const showSmallSample = reviewCount < 5_000;
  const showBasisLine =
    reviewCountEnglish != null && reviewCountEnglish !== reviewCount;

  return (
    <section className="animate-fade-up" data-testid="market-reach">
      <SectionLabel>Market Reach</SectionLabel>
      <div
        className="p-4 rounded-xl"
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
            <div className="grid gap-5 md:grid-cols-2">
              <Stat
                label="Estimated owners"
                value={estimatedOwners!}
                formatter={formatOwners}
                confidence={confidence}
                showSmallSample={showSmallSample}
              />
              <Stat
                label="Estimated gross revenue"
                value={estimatedRevenueUsd!}
                formatter={formatRevenue}
                confidence={confidence}
                showSmallSample={showSmallSample}
              />
            </div>
            {showBasisLine && (
              <p
                className="mt-2 text-xs text-muted-foreground font-mono"
                data-testid="market-reach-basis"
              >
                Based on {reviewCount.toLocaleString()} reviews (all languages)
              </p>
            )}
            <div className="mt-4 flex items-center gap-3 flex-wrap">
              {method && <MethodPill method={method} />}
              <p className="text-xs text-muted-foreground leading-relaxed">
                Based on review count × genre/age/price-adjusted Boxleiter ratio.
                Gross revenue before Steam&rsquo;s 30% cut, refunds, and regional pricing.
              </p>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
