import type { MetadataRoute } from "next";
import { getGames, getGenres, getTopTags } from "@/lib/api";

// Rebuild walks the full catalog; cap regen to once per hour.
export const revalidate = 3600;

const BASE_URL = "https://steampulse.io";
const MIN_REVIEWS = 50;
const URLS_PER_GAME_CHUNK = 5000;
// 60k game capacity vs. ~40k catalog today; each child has its own 6 MB Lambda budget.
const GAME_CHUNK_COUNT = 12;
const TOTAL_CHUNKS = GAME_CHUNK_COUNT + 1; // chunk 0 holds static + genres + tags

export async function generateSitemaps() {
  return Array.from({ length: TOTAL_CHUNKS }, (_, id) => ({ id }));
}

export default async function sitemap(
  { id }: { id: number },
): Promise<MetadataRoute.Sitemap> {
  if (id === 0) return staticAndHubRoutes();
  return gameChunkRoutes(id - 1);
}

async function staticAndHubRoutes(): Promise<MetadataRoute.Sitemap> {
  const routes: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/reports`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/search`, lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE_URL}/about`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.4 },
  ];

  try {
    const genres = await getGenres();
    for (const genre of genres) {
      routes.push({
        url: `${BASE_URL}/genre/${genre.slug}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.7,
      });
    }
  } catch {
    // API may not be available at build time
  }

  try {
    const tags = await getTopTags(100);
    for (const tag of tags) {
      routes.push({
        url: `${BASE_URL}/tag/${tag.slug}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.6,
      });
    }
  } catch {
    // skip
  }

  return routes;
}

async function gameChunkRoutes(chunkIdx: number): Promise<MetadataRoute.Sitemap> {
  const routes: MetadataRoute.Sitemap = [];
  try {
    const result = await getGames({
      sort: "review_count",
      min_reviews: MIN_REVIEWS,
      limit: URLS_PER_GAME_CHUNK,
      offset: chunkIdx * URLS_PER_GAME_CHUNK,
      fields: "compact",
    });
    const games = result.games ?? [];
    const devSlugs = new Set<string>();
    for (const game of games) {
      // lastModified omitted: fields=compact drops the freshness timestamps; byte budget wins over staleness.
      routes.push({
        url: `${BASE_URL}/games/${game.appid}/${game.slug}`,
        changeFrequency: "monthly",
        priority: 0.6,
      });
      if (game.developer) {
        const devSlug = game.developer.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
        if (devSlug && !devSlugs.has(devSlug)) {
          devSlugs.add(devSlug);
          routes.push({
            url: `${BASE_URL}/developer/${devSlug}`,
            changeFrequency: "weekly",
            priority: 0.5,
          });
        }
      }
    }
  } catch {
    // API may not be available at build time
  }
  return routes;
}
