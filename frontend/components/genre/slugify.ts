// Used to build /games/[appid]/[slug] links from benchmark-game names when
// the backend payload only carries appid + name (BenchmarkGame schema).
// Next.js route matching here does not require the URL slug to equal the
// canonical DB slug exactly; a mismatch may still render, but the URL/SEO
// slug can be non-canonical. Non-Latin names strip to empty after the
// ASCII-only regex, so we fall back to "game" to keep the link valid.
export function slugifyName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return slug || "game";
}
