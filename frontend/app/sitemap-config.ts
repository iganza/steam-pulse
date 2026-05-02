export const SITEMAP_BASE_URL = "https://steampulse.io";
// Match actual indexable game count; emitting empty <urlset></urlset> chunks fails Google's schema validation.
export const SITEMAP_GAME_CHUNK_COUNT = 8;
export const SITEMAP_TOTAL_CHUNKS = SITEMAP_GAME_CHUNK_COUNT + 1; // chunk 0 holds static + genres + tags
