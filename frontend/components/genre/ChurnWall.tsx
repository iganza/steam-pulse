import type { ChurnInsight } from "@/lib/types";

interface Props {
  insight: ChurnInsight;
  interpretation: string;
}

// Phase-4 uses typical_dropout_hour === 0 as the sentinel for "no hour
// known" (the prompt explicitly allows 0 when no dropout signal emerges).
// Rendering that as "~0min" would read like a real churn wall at the very
// first minute, which is the opposite of the truth — use an em-dash.
function formatHours(hours: number): string {
  if (hours === 0) return "—";
  if (hours < 1) {
    const minutes = Math.round(hours * 60);
    return `~${minutes}min`;
  }
  // Drop trailing ".0" for whole-hour values — "~8h" reads cleaner than "~8.0h".
  if (hours < 10) {
    const rounded = Math.round(hours * 10) / 10;
    return Number.isInteger(rounded) ? `~${rounded}h` : `~${rounded.toFixed(1)}h`;
  }
  return `~${Math.round(hours)}h`;
}

export function ChurnWall({ insight, interpretation }: Props) {
  const trimmed = interpretation.trim();
  const hasHour = insight.typical_dropout_hour > 0;
  return (
    <section className="mb-16" data-testid="churn-wall">
      <h2 className="font-serif text-2xl md:text-3xl font-bold mb-2" style={{ letterSpacing: "-0.02em" }}>
        The Churn Wall
      </h2>
      <p className="text-sm font-mono mb-8" style={{ color: "var(--muted-foreground)" }}>
        Where players stop — and why.
      </p>

      <div
        className="rounded-xl p-8 md:p-10"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <div
          className="font-serif font-bold leading-none"
          style={{
            fontSize: "clamp(3.5rem, 8vw, 6rem)",
            letterSpacing: "-0.04em",
            color: "var(--teal)",
          }}
          data-testid="churn-wall-stat"
        >
          {formatHours(insight.typical_dropout_hour)}
        </div>
        {!hasHour && (
          <p
            className="mt-2 text-xs font-mono uppercase tracking-widest"
            style={{ color: "var(--muted-foreground)" }}
          >
            No consistent dropout hour in the cohort
          </p>
        )}
        <p className="mt-4 text-lg font-serif">{insight.primary_reason}</p>
        {trimmed && (
          <p
            className="mt-4 text-base max-w-prose"
            data-testid="churn-wall-interpretation"
          >
            {trimmed}
          </p>
        )}
      </div>
    </section>
  );
}
