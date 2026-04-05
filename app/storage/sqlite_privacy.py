from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from app.storage.sqlite_protocol import SQLiteRepositoryProtocol


class SQLitePrivacyMixin(SQLiteRepositoryProtocol):
    def export_verified_user_data(self, verified_user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            user_row = conn.execute(
                """
                SELECT
                    verified_user_id,
                    firstname,
                    lastname,
                    canonical_name,
                    annual_goal_km,
                    email,
                    created_at,
                    updated_at
                FROM verified_users
                WHERE verified_user_id = ?
                """,
                (verified_user_id,),
            ).fetchone()
            if user_row is None:
                return None

            token_rows = conn.execute(
                """
                SELECT
                    token_id,
                    access_token_expires_at,
                    last_sync_utc,
                    created_at,
                    updated_at
                FROM oauth_tokens
                WHERE verified_user_id = ?
                """,
                (verified_user_id,),
            ).fetchall()

            activity_rows = conn.execute(
                """
                SELECT
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
                FROM activities
                WHERE athlete_id = ?
                ORDER BY start_date_utc ASC
                """,
                (verified_user_id,),
            ).fetchall()

        return {
            "verified_user": {
                "verified_user_id": user_row[0],
                "firstname": user_row[1],
                "lastname": user_row[2],
                "canonical_name": user_row[3],
                "annual_goal_km": float(user_row[4]) if user_row[4] is not None else 365.0,
                "email": user_row[5],
                "created_at": user_row[6],
                "updated_at": user_row[7],
            },
            "oauth_tokens": [
                {
                    "token_id": row[0],
                    "access_token_expires_at": row[1],
                    "last_sync_utc": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                }
                for row in token_rows
            ],
            "activities": [
                {
                    "activity_id": row[0],
                    "athlete_id": row[1],
                    "activity_name": row[2],
                    "distance_m": row[3],
                    "moving_time_s": row[4],
                    "elapsed_time_s": row[5],
                    "elevation_gain_m": row[6],
                    "sport_type": row[7],
                    "start_date_utc": row[8],
                    "raw_payload": json.loads(row[9]),
                    "updated_at": row[10],
                }
                for row in activity_rows
            ],
        }

    def delete_verified_user_data(
        self,
        verified_user_id: int,
        *,
        delete_activities: bool = True,
    ) -> dict[str, int]:
        with self._connect() as conn:
            with closing(conn.cursor()) as cursor:
                deleted_activities = 0
                deleted_athletes = 0

                cursor.execute(
                    "DELETE FROM athlete_identity_links WHERE verified_user_id = ?",
                    (verified_user_id,),
                )
                cursor.execute(
                    "DELETE FROM verified_user_clubs WHERE verified_user_id = ?",
                    (verified_user_id,),
                )

                if delete_activities:
                    cursor.execute(
                        "DELETE FROM athlete_identity_links WHERE club_athlete_id = ?",
                        (verified_user_id,),
                    )
                    cursor.execute(
                        "DELETE FROM activities WHERE athlete_id = ?",
                        (verified_user_id,),
                    )
                    deleted_activities = int(cursor.rowcount)

                    cursor.execute(
                        "DELETE FROM athletes WHERE athlete_id = ?",
                        (verified_user_id,),
                    )
                    deleted_athletes = int(cursor.rowcount)

                cursor.execute(
                    "DELETE FROM oauth_tokens WHERE verified_user_id = ?",
                    (verified_user_id,),
                )
                deleted_tokens = int(cursor.rowcount)

                cursor.execute(
                    "UPDATE dsar_audit_log SET verified_user_id = NULL WHERE verified_user_id = ?",
                    (verified_user_id,),
                )

                cursor.execute(
                    "DELETE FROM verified_users WHERE verified_user_id = ?",
                    (verified_user_id,),
                )
                deleted_users = int(cursor.rowcount)

            conn.commit()

        return {
            "verified_users": deleted_users,
            "oauth_tokens": deleted_tokens,
            "activities": deleted_activities,
            "athletes": deleted_athletes,
        }

    def log_dsar_event(
        self,
        *,
        verified_user_id: int | None,
        event_type: str,
        request_source: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        details_json = json.dumps(details) if details is not None else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dsar_audit_log (
                    verified_user_id,
                    event_type,
                    request_source,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (verified_user_id, event_type, request_source, details_json, now),
            )
            conn.commit()

    def list_dsar_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    verified_user_id,
                    event_type,
                    request_source,
                    details_json,
                    created_at
                FROM dsar_audit_log
                ORDER BY event_id ASC
                """
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "verified_user_id": row[1],
                "event_type": row[2],
                "request_source": row[3],
                "details": json.loads(row[4]) if isinstance(row[4], str) else None,
                "created_at": row[5],
            }
            for row in rows
        ]
