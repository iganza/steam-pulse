import type { MetadataRoute } from "next";
import { getGames, getGenres, getTopTags } from "@/lib/api";

// Generated on-demand so it always reflects current DB state
export const dynamic = "force-dynamic";

const BASE_URL = "https://steampulse.io";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const routes: MetadataRoute.Sitemap = [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1,
    },
  ];

  // Games (up to 50k for sitemap; split into sitemap index in production)
  try {
    const games = await getGames({ sort: "review_count", limit: 5000 });
    for (const game of games) {
      routes.push({
        url: `${BASE_URL}/games/${game.appid}/${game.slug}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.8,
      });
      if (game.developer) {
        const devSlug = game.developer.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
        routes.push({
          url: `${BASE_URL}/developer/${devSlug}`,
          lastModified: new Date(),
          changeFrequency: "weekly",
          priority: 0.5,
        });
      }
    }
  } catch {
    // API may not be available at build time — skip
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

  // Deduplicate by URL
  const seen = new Set<string>();
  return routes.filter((r) => {
    if (seen.has(r.url)) return false;
    seen.add(r.url);
    return true;
  });
}
