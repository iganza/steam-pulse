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
