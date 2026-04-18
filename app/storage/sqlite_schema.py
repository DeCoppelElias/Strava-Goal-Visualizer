from __future__ import annotations

import sqlite3

from app.storage.sqlite_protocol import SQLiteRepositoryProtocol


class SQLiteSchemaMixin(SQLiteRepositoryProtocol):
    def _column_exists(self, conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(len(row) > 1 and row[1] == column_name for row in rows)

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS athletes (
                    athlete_id INTEGER PRIMARY KEY,
                    athlete_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activities (
                    activity_id INTEGER PRIMARY KEY,
                    athlete_id INTEGER NOT NULL,
                    activity_name TEXT NOT NULL,
                    distance_m REAL NOT NULL,
                    moving_time_s INTEGER NOT NULL,
                    elapsed_time_s INTEGER NOT NULL,
                    elevation_gain_m REAL NOT NULL,
                    sport_type TEXT NOT NULL,
                    start_date_utc TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (athlete_id) REFERENCES athletes (athlete_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_users (
                    verified_user_id INTEGER PRIMARY KEY,
                    firstname TEXT NOT NULL,
                    lastname TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    annual_goal_km REAL,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._column_exists(conn, "verified_users", "annual_goal_km"):
                conn.execute("ALTER TABLE verified_users ADD COLUMN annual_goal_km REAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_id TEXT PRIMARY KEY,
                    verified_user_id INTEGER NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    accepted_scope TEXT,
                    access_token_expires_at INTEGER,
                    last_sync_utc TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (verified_user_id) REFERENCES verified_users(verified_user_id)
                )
                """
            )
            if not self._column_exists(conn, "oauth_tokens", "accepted_scope"):
                conn.execute("ALTER TABLE oauth_tokens ADD COLUMN accepted_scope TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS athlete_identity_links (
                    club_athlete_id INTEGER PRIMARY KEY,
                    verified_user_id INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    match_type TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (club_athlete_id) REFERENCES athletes(athlete_id),
                    FOREIGN KEY (verified_user_id) REFERENCES verified_users(verified_user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_user_clubs (
                    verified_user_id INTEGER NOT NULL,
                    club_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (verified_user_id, club_id),
                    FOREIGN KEY (verified_user_id) REFERENCES verified_users(verified_user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dsar_audit_log (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    verified_user_id INTEGER,
                    event_type TEXT NOT NULL,
                    request_source TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (verified_user_id) REFERENCES verified_users(verified_user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_pending_states (
                    state TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activities_start_date
                ON activities(start_date_utc)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activities_athlete_date
                ON activities(athlete_id, start_date_utc)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_oauth_tokens_verified_user
                ON oauth_tokens(verified_user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_oauth_tokens_last_sync
                ON oauth_tokens(last_sync_utc)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_verified_user_clubs_club
                ON verified_user_clubs(club_id, verified_user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dsar_verified_user
                ON dsar_audit_log(verified_user_id, created_at)
                """
            )
            conn.commit()
