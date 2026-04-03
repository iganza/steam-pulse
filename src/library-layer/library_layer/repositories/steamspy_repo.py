"""SteamspyRepository -- pure SQL I/O for steamspy_data table."""

from library_layer.repositories.base import BaseRepository


class SteamspyRepository(BaseRepository):
    """CRUD operations for the steamspy_data table."""

    STEAMSPY_FIELDS: tuple[str, ...] = (
        "score_rank",
        "positive",
        "negative",
        "userscore",
        "owners",
        "average_forever",
        "average_2weeks",
        "median_forever",
        "median_2weeks",
        "price",
        "initialprice",
        "discount",
        "ccu",
        "languages",
    )

    def upsert(self, appid: int, data: dict) -> None:
        """Upsert a single row of SteamSpy data for a game."""
        present = [f for f in self.STEAMSPY_FIELDS if f in data]
        if not present:
            return

        cols = ["appid", *present]
        vals = [appid, *(data[f] for f in present)]
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in present)

        sql = f"""
            INSERT INTO steamspy_data ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (appid) DO UPDATE SET {updates}, upserted_at = NOW()
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(vals))
        self.conn.commit()
