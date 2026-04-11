-- depends: 0040_extend_analysis_candidates
--
-- Capture additional Steam fields we've been discarding:
-- - app_catalog: steam_last_modified, price_change_number from GetAppList
-- - games: 14 new columns from appdetails (release_date_raw, content descriptors,
--   controller support, DLC tracking, capsule image, recommendations, support info,
--   legal notice, system requirements)

-- app_catalog: GetAppList metadata
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS steam_last_modified TIMESTAMPTZ;
ALTER TABLE app_catalog ADD COLUMN IF NOT EXISTS price_change_number INTEGER;

-- games: appdetails fields
ALTER TABLE games ADD COLUMN IF NOT EXISTS release_date_raw TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS content_descriptor_ids JSONB;
ALTER TABLE games ADD COLUMN IF NOT EXISTS content_descriptor_notes TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS controller_support TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS dlc_appids JSONB;
ALTER TABLE games ADD COLUMN IF NOT EXISTS parent_appid INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS capsule_image TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS recommendations_total INTEGER;
ALTER TABLE games ADD COLUMN IF NOT EXISTS support_url TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS support_email TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS legal_notice TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_windows TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_mac TEXT;
ALTER TABLE games ADD COLUMN IF NOT EXISTS requirements_linux TEXT;
