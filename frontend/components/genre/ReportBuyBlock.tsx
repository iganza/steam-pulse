"use client";

import { useState } from "react";
import type { ReportSummary, ReportTier } from "@/lib/types";

interface Props {
  report: ReportSummary;
  variant?: "main" | "sidebar";
}

const TIER_COPY: Record<ReportTier, string> = {
  indie: "PDF",
  studio: "PDF + CSV dataset + 1-yr updates",
  publisher: "PDF + CSV + raw JSON + team license",
};

const TIER_LABEL: Record<ReportTier, string> = {
  indie: "Indie",
  studio: "Studio",
  publisher: "Publisher",
};

function formatUsd(cents: number): string {
  const dollars = cents / 100;
  return Number.isInteger(dollars) ? `$${dollars}` : `$${dollars.toFixed(2)}`;
}

function formatShipDate(iso: string): string {
  // Format in UTC so a viewer in e.g. UTC-8 doesn't see the previous day
  // when published_at is stored as UTC midnight. Ship dates are a single
  // canonical day, not a timezone-local moment.
  return new Date(iso).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function ReportBuyBlock({ report, variant = "main" }: Props) {
  const [loading, setLoading] = useState<ReportTier | null>(null);
  const [error, setError] = useState<string | null>(null);

  const checkout = async (tier: ReportTier) => {
    setLoading(tier);
    setError(null);
    try {
      const res = await fetch("/api/checkout/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_slug: report.slug, tier }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { url?: string };
      if (data.url) {
        window.location.href = data.url;
      } else {
        throw new Error("no checkout URL returned");
      }
    } catch {
      setError("Checkout is temporarily unavailable. Please try again in a moment.");
      setLoading(null);
    }
  };

  const actionVerb = report.is_pre_order ? "Pre-order" : "Buy";
  const headingSize = variant === "sidebar" ? "text-lg" : "text-xl md:text-2xl";
  const padding = variant === "sidebar" ? "p-5" : "p-6 md:p-8";

  return (
    <aside
      id={variant === "main" ? "buy" : undefined}
      className={`rounded-xl ${padding}`}
      style={{ background: "var(--card)", border: "1px solid var(--teal)" }}
      data-testid={`report-buy-block-${variant}`}
      data-state={report.is_pre_order ? "pre-order" : "live"}
    >
      <h2 className={`font-serif ${headingSize} font-bold mb-2`} style={{ letterSpacing: "-0.02em" }}>
        Want this as a print-ready report?
      </h2>
      <p className="text-sm mb-5" style={{ color: "var(--muted-foreground)" }}>
        {report.is_pre_order
          ? `${report.display_name} ships ${formatShipDate(report.published_at)}.`
          : `${report.display_name} — available now.`}
      </p>

      <ul className="space-y-2 mb-5 text-sm">
        {report.tiers.map((t) => (
          <li key={t.tier} className="flex items-baseline gap-3">
            <span className="font-mono w-20 shrink-0">{TIER_LABEL[t.tier]}</span>
            <span className="font-mono font-semibold w-14 shrink-0" style={{ color: "var(--teal)" }}>
              {formatUsd(t.price_cents)}
            </span>
            <span style={{ color: "var(--muted-foreground)" }}>{TIER_COPY[t.tier]}</span>
          </li>
        ))}
      </ul>

      <div className={`flex ${variant === "sidebar" ? "flex-col" : "flex-wrap"} gap-2 mb-4`}>
        {report.tiers.map((t) => (
          <button
            key={t.tier}
            type="button"
            onClick={() => checkout(t.tier)}
            disabled={loading !== null}
            className="px-4 py-2.5 rounded-md text-sm font-mono uppercase tracking-widest transition-colors disabled:opacity-60"
            style={{
              background: t.tier === "indie" ? "var(--teal)" : "var(--secondary)",
              color: t.tier === "indie" ? "#0c0c0f" : "var(--foreground)",
              border: "1px solid var(--border)",
            }}
          >
            {loading === t.tier ? "…" : `${actionVerb} ${TIER_LABEL[t.tier]}`}
          </button>
        ))}
      </div>

      <p className="text-xs font-mono" style={{ color: "var(--muted-foreground)" }}>
        {report.is_pre_order
          ? "You'll receive a confirmation email now and the download link on ship date."
          : "Instant download link emailed on purchase."}
      </p>

      {error && (
        <p className="mt-3 text-xs" style={{ color: "var(--negative)" }}>
          {error}
        </p>
      )}
    </aside>
  );
}
