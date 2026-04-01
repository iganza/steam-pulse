import type { Granularity } from "@/lib/types";

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Format a period string returned by the API into a human-friendly label.
 *
 * API period formats:
 *   year    → "2024"       → "2024"
 *   quarter → "2024-Q1"   → "Q1 '24"
 *   month   → "2024-01"   → "Jan '24"
 *   week    → "2024-W03"  → "W03 '24"
 */
export function formatPeriodLabel(period: string, granularity: Granularity): string {
  if (!period) return period;
  if (granularity === "year") return period;

  if (granularity === "quarter") {
    // "2024-Q1" → "Q1 '24"
    const m = period.match(/^(\d{4})-Q(\d)$/);
    if (m) return `Q${m[2]} '${m[1].slice(2)}`;
    return period;
  }

  if (granularity === "month") {
    // "2024-01" → "Jan '24"
    const m = period.match(/^(\d{4})-(\d{2})$/);
    if (m) {
      const monthIdx = parseInt(m[2], 10) - 1;
      return `${MONTH_ABBR[monthIdx] ?? m[2]} '${m[1].slice(2)}`;
    }
    return period;
  }

  if (granularity === "week") {
    // "2024-W03" → "W03 '24"
    const m = period.match(/^(\d{4})-W(\d{2})$/);
    if (m) return `W${m[2]} '${m[1].slice(2)}`;
    return period;
  }

  return period;
}
