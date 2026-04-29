"""WaitlistSuggestionRepository — pure SQL I/O for the waitlist_suggestions table."""

from library_layer.repositories.base import BaseRepository


class WaitlistSuggestionRepository(BaseRepository):
    """CRUD operations for the waitlist_suggestions table."""

    def add(self, email: str, suggestion: str) -> None:
        """Insert a suggestion. Always inserts; multiple per email allowed."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO waitlist_suggestions (email, suggestion)
                VALUES (%s, %s)
                """,
                (email, suggestion),
            )
        self.conn.commit()

    def count(self) -> int:
        """Return total number of suggestion entries."""
        row = self._fetchone("SELECT COUNT(*) AS n FROM waitlist_suggestions", ())
        return int(row["n"]) if row else 0
