from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.sqlite_protocol import SQLiteRepositoryProtocol


class SQLiteOAuthMixin(SQLiteRepositoryProtocol):
    def save_oauth_token(
        self,
        token_id: str,
        verified_user_id: int,
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: int | None,
        accepted_scope: str | None = None,
    ) -> None:
        encrypted_access_token = self._encrypt_token(access_token)
        encrypted_refresh_token = self._encrypt_token(refresh_token)
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_tokens (
                    token_id, verified_user_id, access_token, refresh_token,
                    accepted_scope, access_token_expires_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    accepted_scope = COALESCE(excluded.accepted_scope, oauth_tokens.accepted_scope),
                    access_token_expires_at = excluded.access_token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    token_id,
                    verified_user_id,
                    encrypted_access_token,
                    encrypted_refresh_token,
                    accepted_scope,
                    access_token_expires_at,
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_oauth_tokens(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT token_id, verified_user_id, access_token_expires_at, last_sync_utc "
                "FROM oauth_tokens"
            ).fetchall()
        return [
            {
                "token_id": row[0],
                "verified_user_id": row[1],
                "access_token_expires_at": row[2],
                "last_sync_utc": row[3],
            }
            for row in rows
        ]

    def get_oauth_token(
        self,
        token_id: str,
    ) -> dict[str, str | int | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT access_token, refresh_token, accepted_scope, "
                "access_token_expires_at, verified_user_id "
                "FROM oauth_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "access_token": self._decrypt_token(row[0]) if isinstance(row[0], str) else None,
            "refresh_token": self._decrypt_token(row[1]) if isinstance(row[1], str) else None,
            "accepted_scope": row[2],
            "access_token_expires_at": row[3],
            "verified_user_id": row[4],
        }

    def get_oauth_token_by_verified_user_id(
        self,
        verified_user_id: int,
    ) -> dict[str, str | int | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_id, access_token, refresh_token, accepted_scope, "
                "access_token_expires_at "
                "FROM oauth_tokens WHERE verified_user_id = ?",
                (verified_user_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "token_id": row[0],
            "access_token": self._decrypt_token(row[1]) if isinstance(row[1], str) else None,
            "refresh_token": self._decrypt_token(row[2]) if isinstance(row[2], str) else None,
            "accepted_scope": row[3],
            "access_token_expires_at": row[4],
            "verified_user_id": verified_user_id,
        }

    def set_oauth_last_sync_utc(self, token_id: str, timestamp: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE oauth_tokens SET last_sync_utc = ?, updated_at = ? WHERE token_id = ?",
                (timestamp.isoformat(), datetime.now(UTC).isoformat(), token_id),
            )
            conn.commit()

    def get_oauth_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.token_id,
                    t.verified_user_id,
                    v.firstname,
                    v.lastname,
                    v.email,
                    t.accepted_scope,
                    t.access_token_expires_at,
                    t.last_sync_utc
                FROM oauth_tokens t
                JOIN verified_users v ON v.verified_user_id = t.verified_user_id
                ORDER BY v.firstname, v.lastname
                """
            ).fetchall()
        return [
            {
                "token_id": row[0],
                "verified_user_id": row[1],
                "firstname": row[2],
                "lastname": row[3],
                "email": row[4],
                "accepted_scope": row[5],
                "access_token_expires_at": row[6],
                "last_sync_utc": row[7],
            }
            for row in rows
        ]

    def get_oauth_account_by_verified_user_id(self, verified_user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.token_id,
                    t.verified_user_id,
                    v.firstname,
                    v.lastname,
                    v.email,
                    t.access_token,
                    t.refresh_token,
                    t.accepted_scope,
                    t.access_token_expires_at,
                    t.last_sync_utc,
                    t.created_at
                FROM oauth_tokens t
                JOIN verified_users v ON v.verified_user_id = t.verified_user_id
                WHERE t.verified_user_id = ?
                """,
                (verified_user_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "token_id": row[0],
            "verified_user_id": row[1],
            "firstname": row[2],
            "lastname": row[3],
            "email": row[4],
            "access_token": self._decrypt_token(row[5]) if isinstance(row[5], str) else None,
            "refresh_token": self._decrypt_token(row[6]) if isinstance(row[6], str) else None,
            "accepted_scope": row[7],
            "access_token_expires_at": row[8],
            "last_sync_utc": row[9],
            "created_at": row[10],
        }

    def list_inactive_oauth_accounts(self, cutoff_utc: datetime) -> list[dict[str, Any]]:
        cutoff_iso = cutoff_utc.isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.token_id,
                    t.verified_user_id,
                    v.firstname,
                    v.lastname,
                    v.email,
                    t.access_token,
                    t.refresh_token,
                    t.accepted_scope,
                    t.access_token_expires_at,
                    t.last_sync_utc,
                    t.created_at
                FROM oauth_tokens t
                JOIN verified_users v ON v.verified_user_id = t.verified_user_id
                WHERE COALESCE(t.last_sync_utc, t.created_at) < ?
                ORDER BY COALESCE(t.last_sync_utc, t.created_at) ASC
                """,
                (cutoff_iso,),
            ).fetchall()
        return [
            {
                "token_id": row[0],
                "verified_user_id": row[1],
                "firstname": row[2],
                "lastname": row[3],
                "email": row[4],
                "access_token": self._decrypt_token(row[5]) if isinstance(row[5], str) else None,
                "refresh_token": self._decrypt_token(row[6]) if isinstance(row[6], str) else None,
                "accepted_scope": row[7],
                "access_token_expires_at": row[8],
                "last_sync_utc": row[9],
                "created_at": row[10],
            }
            for row in rows
        ]

    def list_oauth_accounts_in_club(self, club_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.verified_user_id,
                    v.firstname,
                    v.lastname,
                    t.last_sync_utc
                FROM oauth_tokens t
                JOIN verified_users v ON v.verified_user_id = t.verified_user_id
                JOIN verified_user_clubs c ON c.verified_user_id = t.verified_user_id
                WHERE c.club_id = ?
                ORDER BY v.firstname, v.lastname
                """,
                (club_id,),
            ).fetchall()
        return [
            {
                "verified_user_id": row[0],
                "firstname": row[1],
                "lastname": row[2],
                "last_sync_utc": row[3],
            }
            for row in rows
        ]

    def save_pending_oauth_state(self, state: str, ttl_seconds: int = 600) -> None:
        now = datetime.now(UTC)
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO oauth_pending_states (state, expires_at, created_at)
                VALUES (?, ?, ?)
                """,
                (state, expires_at, now.isoformat()),
            )
            conn.commit()

    def consume_pending_oauth_state(self, state: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM oauth_pending_states WHERE state = ?",
                (state,),
            ).fetchone()
            conn.execute(
                "DELETE FROM oauth_pending_states WHERE state = ?",
                (state,),
            )
            conn.commit()
        if row is None:
            return False
        return str(row[0]) >= now

    def purge_expired_oauth_states(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM oauth_pending_states WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
