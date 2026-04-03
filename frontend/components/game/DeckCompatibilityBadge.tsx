"use client";

import { useState } from "react";
import { Gamepad2 } from "lucide-react";
import type { DeckTestResult } from "@/lib/types";

interface DeckCompatibilityBadgeProps {
  compatibility: number | null | undefined;
  testResults?: DeckTestResult[];
  className?: string;
}

const DECK_CONFIG: Record<number, { label: string; bg: string; border: string; color: string }> = {
  3: { label: "Deck Verified", bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.35)", color: "#22c55e" },
  2: { label: "Deck Playable", bg: "rgba(234,179,8,0.12)", border: "rgba(234,179,8,0.35)", color: "#eab308" },
  1: { label: "Deck Unsupported", bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.35)", color: "#ef4444" },
};

function formatTestResult(locToken: string): string {
  const name = locToken.replace("#SteamDeckVerified_TestResult_", "");
  return name.replace(/([A-Z])/g, " $1").trim();
}

function testResultColor(displayType: number): string {
  if (displayType === 2 || displayType === 4) return "#22c55e";
  if (displayType === 3) return "#eab308";
  if (displayType === 1) return "#ef4444";
  return "var(--muted-foreground)";
}

export function DeckCompatibilityBadge({
  compatibility,
  testResults,
  className = "",
}: DeckCompatibilityBadgeProps) {
  const [expanded, setExpanded] = useState(false);
  const status = compatibility ?? 0;
  const config = DECK_CONFIG[status];
  if (!config) return null;

  const hasResults = testResults && testResults.length > 0;

  return (
    <div className={`relative inline-block ${className}`}>
      <button
        type="button"
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono uppercase tracking-widest cursor-pointer"
        style={{
          background: config.bg,
          border: `1px solid ${config.border}`,
          color: config.color,
        }}
        onClick={() => hasResults && setExpanded(!expanded)}
        data-testid="deck-badge"
        aria-expanded={hasResults ? expanded : undefined}
      >
        <Gamepad2 className="w-3 h-3" />
        {config.label}
      </button>
      {expanded && hasResults && (
        <div
          className="absolute z-50 top-full left-0 mt-2 min-w-[280px] rounded-lg p-3 text-xs space-y-1.5"
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            boxShadow: "0 4px 24px rgba(0,0,0,0.4)",
          }}
          data-testid="deck-test-results"
        >
          {testResults.map((item, i) => (
            <div key={i} className="flex items-start gap-2">
              <span style={{ color: testResultColor(item.display_type) }}>
                {item.display_type === 1 ? "\u2716" : item.display_type === 3 ? "\u26A0" : "\u2714"}
              </span>
              <span className="text-foreground/80">
                {formatTestResult(item.loc_token)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
