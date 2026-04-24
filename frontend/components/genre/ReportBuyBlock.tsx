"use client";

import { useState } from "react";
import type { ReportSummary } from "@/lib/types";

interface Props {
  report: ReportSummary;
  variant?: "main" | "sidebar";
}

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkout = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/checkout/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_slug: report.slug }),
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
      setLoading(false);
    }
  };

  const actionVerb = report.is_pre_order ? "Pre-order" : "Buy";
  const headingSize = variant === "sidebar" ? "text-lg" : "text-xl md:text-2xl";
  const padding = variant === "sidebar" ? "p-5" : "p-6 md:p-8";
  const priceLabel = formatUsd(report.price_cents);

  return (
    <aside
      id={variant === "main" ? "buy" : undefined}
      className={`rounded-xl ${padding}`}
      style={{ background: "var(--card)", border: "1px solid var(--teal)" }}
      data-testid={`report-buy-block-${variant}`}
      data-state={report.is_pre_order ? "pre-order" : "live"}
    >
      <h2 className={`font-serif ${headingSize} font-bold mb-2`} style={{ letterSpacing: "-0.02em" }}>
        The full report — your next 8 design moves
      </h2>
      <p className="text-sm mb-4" style={{ color: "var(--muted-foreground)" }}>
        {report.is_pre_order
          ? `${report.display_name} ships ${formatShipDate(report.published_at)}.`
          : `${report.display_name} — available now.`}
      </p>

      <ul className="space-y-1.5 mb-5 text-sm" style={{ color: "var(--muted-foreground)" }}>
        <li>Hand-written deep-dives on the 5 benchmark games</li>
        <li>Strategic recommendations — ranked design moves with data citations</li>
        <li>Dev priorities as a prioritised plan</li>
        <li>Executive summary + full friction / wishlist lists</li>
        <li>CSV dataset with source_appid columns</li>
      </ul>

      <button
        type="button"
        onClick={checkout}
        disabled={loading}
        className="w-full px-4 py-3 rounded-md text-sm font-mono uppercase tracking-widest transition-colors disabled:opacity-60 mb-4"
        style={{
          background: "var(--teal)",
          color: "#0c0c0f",
          border: "1px solid var(--border)",
        }}
      >
        {loading ? "…" : `${actionVerb} — ${priceLabel}`}
      </button>

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
