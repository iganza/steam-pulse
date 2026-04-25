-- Delta gate for review-fetch: store the English review count at the last
-- successful review fetch so the dispatcher can skip refetches whose net-new
-- review delta is below REFRESH_REVIEWS_MIN_DELTA.

ALTER TABLE app_catalog
  ADD COLUMN IF NOT EXISTS review_count_at_last_fetch INTEGER NOT NULL DEFAULT 0;

-- Backfill from current English count for already-fetched games so day-of-deploy
-- doesn't treat every previously-fetched game as way overdue. Day-1 delta is 0;
-- the gate naturally trips again as new reviews accrue.
UPDATE app_catalog ac
SET    review_count_at_last_fetch = COALESCE(g.review_count_english, 0)
FROM   games g
WHERE  ac.appid = g.appid
  AND  ac.review_crawled_at IS NOT NULL;
