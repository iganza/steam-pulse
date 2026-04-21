"use client";

import { useState } from "react";
import type { ReportSummary, ReportTier } from "@/lib/types";

interface Props {
  report: ReportSummary | null;
  placement: "body" | "sidebar";
}

const TIER_LABEL: Record<ReportTier, string> = {
  indie: "Indie",
  studio: "Studio",
  publisher: "Publisher",
};

const TIER_DESC: Record<ReportTier, string> = {
  indie: "PDF",
  studio: "PDF + CSV dataset + 1-yr updates",
  publisher: "PDF + CSV + raw JSON + team license",
};

function formatPrice(cents: number): string {
  const dollars = Math.round(cents / 100);
  return `$${dollars}`;
}

function formatShipDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function ReportBlock({ report, placement }: Props) {
  const [pending, setPending] = useState<ReportTier | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!report) return null;

  const isPreOrder = report.is_pre_order;
  const verb = isPreOrder ? "Pre-order" : "Buy";

  async function onPurchase(tier: ReportTier) {
    setPending(tier);
    setError(null);
    try {
      const res = await fetch("/api/checkout/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_slug: report!.slug, tier }),
      });
      if (!res.ok) {
        setError("Checkout isn't live yet — try again shortly.");
        return;
      }
      const data = (await res.json()) as { url?: string };
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError("Checkout isn't live yet — try again shortly.");
      }
    } catch {
      setError("Checkout isn't live yet — try again shortly.");
    } finally {
      setPending(null);
    }
  }

  const wrapper =
    placement === "sidebar"
      ? "rounded-xl p-5 text-sm"
      : "rounded-xl p-6 md:p-8";

  return (
    <aside
      aria-labelledby={`report-block-${placement}`}
      className={wrapper}
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <h2
        id={`report-block-${placement}`}
        className="font-serif text-lg md:text-xl font-semibold mb-2"
      >
        Want this as a print-ready report?
      </h2>
      <p className="text-sm text-foreground/75 mb-5">
        {isPreOrder ? (
          <>
            {report.display_name} ships {formatShipDate(report.published_at)}.
          </>
        ) : (
          <>{report.display_name} — available now.</>
        )}
      </p>
      <ul className="space-y-3 mb-5 list-none p-0">
        {report.tiers.map((t) => (
          <li key={t.tier} className="flex items-baseline gap-3 text-sm">
            <span className="font-serif font-semibold w-24 shrink-0">
              {TIER_LABEL[t.tier]}
            </span>
            <span className="font-mono tabular-nums text-foreground/90 w-14 shrink-0">
              {formatPrice(t.price_cents)}
            </span>
            <span className="text-muted-foreground">{TIER_DESC[t.tier]}</span>
          </li>
        ))}
      </ul>
      <div className={placement === "sidebar" ? "flex flex-col gap-2" : "flex flex-wrap gap-2"}>
        {report.tiers.map((t) => (
          <button
            key={t.tier}
            type="button"
            onClick={() => onPurchase(t.tier)}
            disabled={pending !== null}
            className="inline-flex items-center justify-center px-4 py-2 rounded-md text-sm font-mono border border-border bg-background hover:border-foreground/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {pending === t.tier ? "Redirecting…" : `${verb} ${TIER_LABEL[t.tier]}`}
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs font-mono text-muted-foreground">
        {isPreOrder
          ? "You'll receive a confirmation email now and the download link on ship date."
          : "Instant download link emailed on purchase."}
      </p>
      {error && (
        <p role="alert" className="mt-3 text-xs font-mono text-red-400">
          {error}
        </p>
      )}
    </aside>
  );
}
