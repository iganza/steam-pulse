-- depends: 0056_waitlist_suggestions

ALTER TABLE waitlist
ADD COLUMN confirmation_email_sent_at TIMESTAMPTZ;
