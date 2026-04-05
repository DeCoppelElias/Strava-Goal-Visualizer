from __future__ import annotations

from datetime import UTC, datetime

from app.storage.sqlite_protocol import SQLiteRepositoryProtocol
from app.strava.models import canonical_athlete_name


class SQLiteUserMixin(SQLiteRepositoryProtocol):
    def save_verified_user(
        self,
        verified_user_id: int,
        firstname: str,
        lastname: str,
        email: str | None = None,
    ) -> None:
        canonical = canonical_athlete_name(firstname, lastname)
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO verified_users
                (
                    verified_user_id, firstname, lastname, canonical_name,
                    email, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(verified_user_id) DO UPDATE SET
                    firstname = excluded.firstname,
                    lastname = excluded.lastname,
                    canonical_name = excluded.canonical_name,
                    email = excluded.email,
                    updated_at = excluded.updated_at
                """,
                (verified_user_id, firstname, lastname, canonical, email, now, now),
            )
            conn.commit()

    def get_user_annual_goal(
        self,
        verified_user_id: int,
        *,
        default_goal_km: float = 365.0,
    ) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT annual_goal_km FROM verified_users WHERE verified_user_id = ?",
                (verified_user_id,),
            ).fetchone()

        if row is None or row[0] is None:
            return float(default_goal_km)
        return float(row[0])

    def get_user_annual_goals(
        self,
        verified_user_ids: list[int],
        *,
        default_goal_km: float = 365.0,
    ) -> dict[int, float]:
        unique_ids = sorted(set(verified_user_ids))
        if not unique_ids:
            return {}

        placeholders = ",".join(["?"] * len(unique_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT verified_user_id, annual_goal_km
                FROM verified_users
                WHERE verified_user_id IN ({placeholders})
                """,
                tuple(unique_ids),
            ).fetchall()

        goal_map: dict[int, float] = {
            int(user_id): float(default_goal_km)
            for user_id in unique_ids
        }
        for row in rows:
            user_id = int(row[0])
            goal_map[user_id] = float(row[1]) if row[1] is not None else float(default_goal_km)
        return goal_map

    def update_user_annual_goal(
        self,
        verified_user_id: int,
        annual_goal_km: float,
        *,
        max_annual_goal_km: float = 100000.0,
    ) -> None:
        if annual_goal_km <= 0:
            raise ValueError("annual_goal_km must be greater than 0")
        if annual_goal_km > max_annual_goal_km:
            raise ValueError(
                f"annual_goal_km must be <= {float(max_annual_goal_km):.1f}"
            )

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE verified_users
                SET annual_goal_km = ?, updated_at = ?
                WHERE verified_user_id = ?
                """,
                (annual_goal_km, datetime.now(UTC).isoformat(), verified_user_id),
            )
            conn.commit()

    def replace_verified_user_clubs(self, verified_user_id: int, club_ids: list[int]) -> None:
        now = datetime.now(UTC).isoformat()
        unique_club_ids = sorted(set(club_ids))
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM verified_user_clubs WHERE verified_user_id = ?",
                (verified_user_id,),
            )
            for club_id in unique_club_ids:
                conn.execute(
                    """
                    INSERT INTO verified_user_clubs (verified_user_id, club_id, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (verified_user_id, club_id, now),
                )
            conn.commit()

    def list_verified_user_club_ids(self, verified_user_id: int) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT club_id FROM verified_user_clubs "
                "WHERE verified_user_id = ? ORDER BY club_id",
                (verified_user_id,),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def is_verified_user_in_club(self, verified_user_id: int, club_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM verified_user_clubs
                WHERE verified_user_id = ? AND club_id = ?
                """,
                (verified_user_id, club_id),
            ).fetchone()
        return row is not None

    def list_verified_users(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT verified_user_id, firstname, lastname, canonical_name, email "
                "FROM verified_users ORDER BY firstname, lastname"
            ).fetchall()
        return [
            {
                "verified_user_id": row[0],
                "firstname": row[1],
                "lastname": row[2],
                "canonical_name": row[3],
                "email": row[4],
            }
            for row in rows
        ]
