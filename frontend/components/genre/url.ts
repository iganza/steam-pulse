// Canonical URL for a genre synthesis page. Aligns with the repo-wide
// no-trailing-slash convention so `<link rel="canonical">`, JSON-LD `@id`,
// OG URL, and the Share buttons all emit the same string.
export function genrePageUrl(slug: string): string {
  return `https://steampulse.io/genre/${slug}`;
}
