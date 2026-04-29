-- depends: 0056_waitlist_suggestions

ALTER TABLE waitlist
ADD COLUMN IF NOT EXISTS confirmation_email_sent_at TIMESTAMPTZ;
