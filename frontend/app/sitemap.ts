import type { MetadataRoute } from "next";
import { getGames, getGenres, getTopTags } from "@/lib/api";
import { slugify } from "@/lib/format";

// Rebuild walks the full catalog; cap regen to once per hour.
export const revalidate = 3600;

const BASE_URL = "https://steampulse.io";
const MIN_REVIEWS = 50;
const URLS_PER_GAME_CHUNK = 5000;
// 60k game capacity; each child has its own 6 MB Lambda budget. Bump when the indexable catalog approaches ~50k games.
const GAME_CHUNK_COUNT = 12;
const TOTAL_CHUNKS = GAME_CHUNK_COUNT + 1; // chunk 0 holds static + genres + tags

function parseTimestamp(ts: string | null | undefined): Date | undefined {
  if (typeof ts !== "string" || ts.length === 0) return undefined;
  const t = new Date(ts).getTime();
  return Number.isNaN(t) ? undefined : new Date(t);
}

export async function generateSitemaps() {
  return Array.from({ length: TOTAL_CHUNKS }, (_, id) => ({ id }));
}

export default async function sitemap(
  { id }: { id: number | string },
): Promise<MetadataRoute.Sitemap> {
  const sitemapId = Number(id);
  if (sitemapId === 0) return staticAndHubRoutes();
  return gameChunkRoutes(sitemapId - 1);
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
      routes.push({
        url: `${BASE_URL}/games/${game.appid}/${game.slug}`,
        lastModified: parseTimestamp(game.last_analyzed),
        changeFrequency: "monthly",
        priority: 0.6,
      });
      const devSlug = game.developer_slug || (game.developer ? slugify(game.developer) : "");
      if (devSlug && !devSlugs.has(devSlug)) {
        devSlugs.add(devSlug);
        routes.push({
          url: `${BASE_URL}/developer/${devSlug}`,
          changeFrequency: "weekly",
          priority: 0.5,
        });
      }
    }
  } catch {
    // API may not be available at build time
  }
  return routes;
}
