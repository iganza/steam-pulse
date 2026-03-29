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
