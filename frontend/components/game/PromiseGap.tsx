"use client";

import { AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import type { StorePageAlignment } from "@/lib/types";

interface PromiseGapProps {
  alignment: StorePageAlignment;
}

type Verdict = "validated" | "underdelivered" | "hidden_strength";

interface PromiseRow {
  claim: string;
  verdict: Verdict;
}

const VERDICT_STYLE: Record<
  Verdict,
  { label: string; color: string; bg: string; border: string; Icon: typeof CheckCircle2 }
> = {
  validated: {
    label: "VALIDATED",
    color: "var(--positive)",
    bg: "rgba(34,197,94,0.08)",
    border: "rgba(34,197,94,0.2)",
    Icon: CheckCircle2,
  },
  underdelivered: {
    label: "UNDERDELIVERED",
    color: "var(--negative)",
    bg: "rgba(239,68,68,0.08)",
    border: "rgba(239,68,68,0.15)",
    Icon: AlertTriangle,
  },
  hidden_strength: {
    label: "HIDDEN STRENGTH",
    color: "var(--gem)",
    bg: "rgba(201,151,60,0.08)",
    border: "rgba(201,151,60,0.2)",
    Icon: Sparkles,
  },
};

const AUDIENCE_STYLE: Record<
  StorePageAlignment["audience_match"],
  { label: string; color: string; bg: string; border: string }
> = {
  aligned: {
    label: "ALIGNED",
    color: "var(--positive)",
    bg: "rgba(34,197,94,0.08)",
    border: "rgba(34,197,94,0.2)",
  },
  partial_mismatch: {
    label: "PARTIAL MISMATCH",
    color: "var(--gem)",
    bg: "rgba(201,151,60,0.08)",
    border: "rgba(201,151,60,0.2)",
  },
  significant_mismatch: {
    label: "MISMATCH",
    color: "var(--negative)",
    bg: "rgba(239,68,68,0.08)",
    border: "rgba(239,68,68,0.15)",
  },
};

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const style = VERDICT_STYLE[verdict];
  return (
    <span
      className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded-full flex-shrink-0"
      style={{ background: style.bg, border: `1px solid ${style.border}`, color: style.color }}
    >
      {style.label}
    </span>
  );
}

function PromiseRowCard({ row }: { row: PromiseRow }) {
  const { Icon, color } = VERDICT_STYLE[row.verdict];
  return (
    <div
      className="p-4 rounded-xl flex flex-col sm:flex-row sm:items-start gap-3"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-start gap-3 flex-1 min-w-0">
        <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color }} />
        <span className="text-base text-foreground/80 leading-relaxed">{row.claim}</span>
      </div>
      <VerdictBadge verdict={row.verdict} />
    </div>
  );
}

export function PromiseGap({ alignment }: PromiseGapProps) {
  const rows: PromiseRow[] = [
    ...alignment.promises_delivered.map((claim) => ({ claim, verdict: "validated" as const })),
    ...alignment.promises_broken.map((claim) => ({ claim, verdict: "underdelivered" as const })),
    ...alignment.hidden_strengths.map((claim) => ({ claim, verdict: "hidden_strength" as const })),
  ];

  if (rows.length === 0) return null;

  const audience = AUDIENCE_STYLE[alignment.audience_match];

  return (
    <div data-testid="promise-gap">
      <div className="space-y-3">
        {rows.map((row, i) => (
          <PromiseRowCard key={i} row={row} />
        ))}
      </div>

      <div
        className="mt-6 p-5 rounded-xl"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3 mb-2">
          <span
            className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded-full flex-shrink-0"
            style={{
              background: audience.bg,
              border: `1px solid ${audience.border}`,
              color: audience.color,
            }}
          >
            {audience.label}
          </span>
          <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
            Audience Match
          </p>
        </div>
        <p className="text-base text-foreground/80 leading-relaxed">
          {alignment.audience_match_note}
        </p>
      </div>
    </div>
  );
}
