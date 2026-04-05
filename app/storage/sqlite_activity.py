from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.storage.query_scope import build_activity_scope_clause
from app.storage.sqlite_protocol import SQLiteRepositoryProtocol
from app.strava.models import ClubActivity


class SQLiteActivityMixin(SQLiteRepositoryProtocol):
    def upsert_activities(self, activities: list[ClubActivity]) -> int:
        if not activities:
            return 0

        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            with closing(conn.cursor()) as cursor:
                for activity in activities:
                    cursor.execute(
                        """
                        INSERT INTO athletes (athlete_id, athlete_name, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(athlete_id) DO UPDATE SET
                            athlete_name = excluded.athlete_name,
                            updated_at = excluded.updated_at
                        """,
                        (activity.athlete_id, activity.athlete_name, now),
                    )

                    cursor.execute(
                        """
                        INSERT INTO activities (
                            activity_id,
                            athlete_id,
                            activity_name,
                            distance_m,
                            moving_time_s,
                            elapsed_time_s,
                            elevation_gain_m,
                            sport_type,
                            start_date_utc,
                            raw_json,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(activity_id) DO UPDATE SET
                            athlete_id = excluded.athlete_id,
                            activity_name = excluded.activity_name,
                            distance_m = excluded.distance_m,
                            moving_time_s = excluded.moving_time_s,
                            elapsed_time_s = excluded.elapsed_time_s,
                            elevation_gain_m = excluded.elevation_gain_m,
                            sport_type = excluded.sport_type,
                            start_date_utc = excluded.start_date_utc,
                            raw_json = excluded.raw_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            activity.activity_id,
                            activity.athlete_id,
                            activity.name,
                            activity.distance_m,
                            activity.moving_time_s,
                            activity.elapsed_time_s,
                            activity.elevation_gain_m,
                            activity.sport_type,
                            activity.start_date_utc.isoformat(),
                            json.dumps(activity.raw_payload),
                            now,
                        ),
                    )
            conn.commit()

        return len(activities)

    def get_last_sync_utc(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_value FROM sync_state WHERE state_key = ?",
                ("last_sync_utc",),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def set_last_sync_utc(self, timestamp: datetime) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value = excluded.state_value,
                    updated_at = excluded.updated_at
                """,
                ("last_sync_utc", timestamp.isoformat(), now),
            )
            conn.commit()

    def fetch_activities_df(
        self,
        start_date_utc: datetime,
        end_date_utc: datetime,
        *,
        verified_user_id: int | None = None,
        club_id: int | None = None,
    ) -> pd.DataFrame:
        query = """
            SELECT
                a.activity_id,
                a.athlete_id,
                t.athlete_name,
                a.activity_name,
                a.distance_m,
                a.moving_time_s,
                a.elapsed_time_s,
                a.elevation_gain_m,
                a.sport_type,
                a.start_date_utc
            FROM activities a
            JOIN athletes t ON t.athlete_id = a.athlete_id
            WHERE a.start_date_utc >= ? AND a.start_date_utc <= ?
        """

        params: list[Any] = [start_date_utc.isoformat(), end_date_utc.isoformat()]
        scope_clause, scope_params = build_activity_scope_clause(
            athlete_column="a.athlete_id",
            verified_user_id=verified_user_id,
            club_id=club_id,
        )
        query += scope_clause
        params.extend(scope_params)

        query += " ORDER BY a.start_date_utc ASC"

        with self._connect() as conn:
            return pd.read_sql_query(
                query,
                conn,
                params=tuple(params),
            )

    def list_activity_years(
        self,
        *,
        verified_user_id: int | None = None,
        club_id: int | None = None,
    ) -> list[int]:
        query = """
            SELECT DISTINCT CAST(strftime('%Y', start_date_utc) AS INTEGER) AS year
            FROM activities
            WHERE start_date_utc IS NOT NULL
        """
        params: list[Any] = []
        scope_clause, scope_params = build_activity_scope_clause(
            athlete_column="athlete_id",
            verified_user_id=verified_user_id,
            club_id=club_id,
        )
        query += scope_clause
        params.extend(scope_params)

        query += " ORDER BY year DESC"

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [int(row[0]) for row in rows if row[0] is not None]

    def list_athletes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT athlete_id, athlete_name FROM athletes ORDER BY athlete_name"
            ).fetchall()
        return [{"athlete_id": row[0], "athlete_name": row[1]} for row in rows]

    def count_activities_older_than(self, cutoff_utc: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM activities WHERE start_date_utc < ?",
                (cutoff_utc.isoformat(),),
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def delete_activities_older_than(self, cutoff_utc: datetime) -> dict[str, int]:
        with self._connect() as conn:
            deleted_activities = conn.execute(
                "DELETE FROM activities WHERE start_date_utc < ?",
                (cutoff_utc.isoformat(),),
            ).rowcount
            # Keep athletes referenced by remaining activities or identity links.
            deleted_athletes = conn.execute(
                """
                DELETE FROM athletes
                WHERE athlete_id NOT IN (SELECT athlete_id FROM activities)
                  AND athlete_id NOT IN (SELECT club_athlete_id FROM athlete_identity_links)
                """
            ).rowcount
            conn.commit()

        return {
            "activities": int(deleted_activities if deleted_activities is not None else 0),
            "athletes": int(deleted_athletes if deleted_athletes is not None else 0),
        }

    def save_identity_link(
        self,
        club_athlete_id: int,
        verified_user_id: int,
        confidence: float,
        match_type: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO athlete_identity_links (
                    club_athlete_id, verified_user_id, confidence, match_type, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(club_athlete_id) DO UPDATE SET
                    verified_user_id = excluded.verified_user_id,
                    confidence = excluded.confidence,
                    match_type = excluded.match_type,
                    updated_at = excluded.updated_at
                """,
                (club_athlete_id, verified_user_id, confidence, match_type, now),
            )
            conn.commit()

    def get_identity_links(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    l.club_athlete_id,
                    a.athlete_name,
                    l.verified_user_id,
                    v.firstname,
                    v.lastname,
                    l.confidence,
                    l.match_type
                FROM athlete_identity_links l
                JOIN athletes a ON a.athlete_id = l.club_athlete_id
                JOIN verified_users v ON v.verified_user_id = l.verified_user_id
                ORDER BY l.confidence DESC, a.athlete_name ASC
                """
            ).fetchall()
        return [
            {
                "club_athlete_id": row[0],
                "athlete_name": row[1],
                "verified_user_id": row[2],
                "verified_firstname": row[3],
                "verified_lastname": row[4],
                "confidence": row[5],
                "match_type": row[6],
            }
            for row in rows
        ]
