import type { MetadataRoute } from "next";
import { getGames, getGenres, getTopTags } from "@/lib/api";
import type { Game } from "@/lib/types";

// Regenerate at most once per hour; a single sitemap rebuild walks the full
// catalog, so per-request generation would waste DB and CPU.
export const revalidate = 3600;

const BASE_URL = "https://steampulse.io";
const MIN_REVIEWS = 50;
// Stay under the 50k-URL sitemap spec limit with headroom for hub routes
// added after the game loop. HUB_RESERVE is the budget held back from the
// game+developer loop so genre/tag entries always make it in.
const MAX_URLS = 49000;
const HUB_RESERVE = 500;
const GAME_LOOP_CAP = MAX_URLS - HUB_RESERVE;

function gameLastModified(game: Game): Date | undefined {
  const candidates = [
    game.reviews_completed_at,
    game.review_crawled_at,
    game.tags_crawled_at,
    game.last_analyzed,
    game.meta_crawled_at,
  ];
  let maxTime: number | undefined;
  for (const c of candidates) {
    if (typeof c !== "string" || c.length === 0) continue;
    const t = new Date(c).getTime();
    if (Number.isNaN(t)) continue;
    if (maxTime === undefined || t > maxTime) maxTime = t;
  }
  return maxTime === undefined ? undefined : new Date(maxTime);
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const routes: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/reports`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/search`, lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE_URL}/about`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.4 },
  ];

  // Games — paginate through all indexable games, respecting the total URL cap
  try {
    let offset = 0;
    const limit = 1000;
    const devSlugs = new Set<string>();
    while (routes.length < GAME_LOOP_CAP) {
      const result = await getGames({
        sort: "review_count",
        limit,
        offset,
        min_reviews: MIN_REVIEWS,
      });
      const games = result.games ?? [];
      if (games.length === 0) break;
      for (const game of games) {
        if (routes.length >= GAME_LOOP_CAP) break;
        routes.push({
          url: `${BASE_URL}/games/${game.appid}/${game.slug}`,
          lastModified: gameLastModified(game),
          changeFrequency: "monthly",
          priority: 0.6,
        });
        if (game.developer && routes.length < GAME_LOOP_CAP) {
          const devSlug = game.developer.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
          if (!devSlugs.has(devSlug)) {
            devSlugs.add(devSlug);
            routes.push({
              url: `${BASE_URL}/developer/${devSlug}`,
              changeFrequency: "weekly",
              priority: 0.5,
            });
          }
        }
      }
      if (games.length < limit) break;
      offset += limit;
    }
  } catch {
    // API may not be available at build time
  }

  // Genres
  try {
    const genres = await getGenres();
    for (const genre of genres) {
      if (routes.length >= MAX_URLS) break;
      routes.push({
        url: `${BASE_URL}/genre/${genre.slug}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.7,
      });
    }
  } catch {
    // skip
  }

  // Tags
  try {
    const tags = await getTopTags(100);
    for (const tag of tags) {
      if (routes.length >= MAX_URLS) break;
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
