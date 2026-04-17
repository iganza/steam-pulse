import type { MetadataRoute } from "next";

const SEARCH_BOTS = ["Googlebot", "Bingbot", "DuckDuckBot"];
const AI_BOTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot"];
const SOCIAL_BOTS = ["Twitterbot", "facebookexternalhit", "LinkedInBot"];
const DISALLOW = ["/api/", "/admin/"];

export default function robots(): MetadataRoute.Robots {
  const named = [...SEARCH_BOTS, ...AI_BOTS, ...SOCIAL_BOTS].map((userAgent) => ({
    userAgent,
    allow: "/",
    disallow: DISALLOW,
  }));
  return {
    rules: [...named, { userAgent: "*", allow: "/", disallow: DISALLOW }],
    sitemap: "https://steampulse.io/sitemap.xml",
  };
}
