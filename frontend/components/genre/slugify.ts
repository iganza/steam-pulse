// Used to build /games/[appid]/[slug] links from benchmark-game names when
// the backend payload only carries appid + name (BenchmarkGame schema).
// Next.js routes don't require the slug to match the canonical DB slug
// exactly — a mismatch would typically redirect, not 404.
export function slugifyName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
