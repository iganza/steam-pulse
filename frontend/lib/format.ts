/** Short relative-time string ("2h ago", "3d ago") from an ISO timestamp. */
export function relativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 30) return `${Math.round(diffSec / 86400)}d ago`;
  if (diffSec < 86400 * 365) return `${Math.round(diffSec / (86400 * 30))}mo ago`;
  return `${Math.round(diffSec / (86400 * 365))}y ago`;
}

/** URL-safe slug — lowercase, non-alphanumerics collapsed to "-". */
export function slugify(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

/**
 * Parse a YYYY-MM-DD date string as a LOCAL date (not UTC).
 *
 * `new Date("2026-04-08")` parses as UTC midnight, then any subsequent
 * `toLocaleDateString()` in a west-of-UTC timezone formats it as the previous
 * day. Use this helper for any `release_date` / `DATE`-typed field coming from
 * Postgres so the user sees the same calendar day the developer entered on Steam.
 *
 * Duplicated copies exist in `components/analytics/DeveloperPortfolio.tsx` and
 * `PublisherPortfolio.tsx`; prefer importing from here for new code.
 */
export function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}
