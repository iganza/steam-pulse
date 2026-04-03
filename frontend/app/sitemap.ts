import type { MetadataRoute } from "next";
import { getGames, getGenres, getTopTags } from "@/lib/api";

// Generated on-demand so it always reflects current DB state
export const dynamic = "force-dynamic";

const BASE_URL = "https://steampulse.io";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const routes: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/search`, lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE_URL}/trending`, lastModified: new Date(), changeFrequency: "daily", priority: 0.7 },
    { url: `${BASE_URL}/new-releases`, lastModified: new Date(), changeFrequency: "daily", priority: 0.7 },
    { url: `${BASE_URL}/pro`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.5 },
  ];

  // Games — paginate through all games (up to 49k for single sitemap)
  try {
    let offset = 0;
    const limit = 1000;
    const devSlugs = new Set<string>();
    while (offset < 49000) {
      const result = await getGames({ sort: "review_count", limit, offset });
      const games = result.games ?? [];
      if (games.length === 0) break;
      for (const game of games) {
        routes.push({
          url: `${BASE_URL}/games/${game.appid}/${game.slug}`,
          changeFrequency: "monthly",
          priority: 0.6,
        });
        if (game.developer) {
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
