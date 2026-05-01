export const SITEMAP_BASE_URL = "https://steampulse.io";
// 60k game capacity; each child has its own 6 MB Lambda budget. Bump when the indexable catalog approaches ~50k games.
export const SITEMAP_GAME_CHUNK_COUNT = 12;
export const SITEMAP_TOTAL_CHUNKS = SITEMAP_GAME_CHUNK_COUNT + 1; // chunk 0 holds static + genres + tags
