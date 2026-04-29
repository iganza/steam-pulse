"""WaitlistRepository — pure SQL I/O for the waitlist table."""

from library_layer.repositories.base import BaseRepository


class WaitlistRepository(BaseRepository):
    """CRUD operations for the waitlist table."""

    def add(self, email: str) -> bool:
        """Insert email into the waitlist. Returns True if inserted, False if already exists."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO waitlist (email)
                VALUES (%s)
                ON CONFLICT (email) DO NOTHING
                """,
                (email,),
            )
            inserted = cur.rowcount > 0
        self.conn.commit()
        return inserted

    def count(self) -> int:
        """Return total number of waitlist entries."""
        row = self._fetchone("SELECT COUNT(*) AS n FROM waitlist", ())
        return int(row["n"]) if row else 0

    def needs_confirmation(self, email: str) -> bool:
        """True if the row exists and confirmation_email_sent_at IS NULL."""
        row = self._fetchone(
            "SELECT 1 FROM waitlist WHERE email = %s AND confirmation_email_sent_at IS NULL",
            (email,),
        )
        return row is not None

    def claim_confirmation_send(self, email: str) -> bool:
        """Atomically claim the right to send the confirmation email.

        The conditional UPDATE is the lock: only one concurrent caller can flip NULL to NOW().
        Caller MUST send the email after claiming; on failure call release_confirmation_claim.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE waitlist
                SET confirmation_email_sent_at = NOW()
                WHERE email = %s AND confirmation_email_sent_at IS NULL
                """,
                (email,),
            )
            claimed = cur.rowcount > 0
        self.conn.commit()
        return claimed

    def release_confirmation_claim(self, email: str) -> None:
        """Roll back a claim after a Resend failure so SQS retry can re-attempt."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE waitlist SET confirmation_email_sent_at = NULL WHERE email = %s",
                (email,),
            )
        self.conn.commit()
