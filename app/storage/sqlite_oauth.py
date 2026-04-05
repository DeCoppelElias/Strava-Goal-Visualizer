from __future__ import annotations

from datetime import UTC, datetime
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
    ) -> None:
        encrypted_access_token = self._encrypt_token(access_token)
        encrypted_refresh_token = self._encrypt_token(refresh_token)
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_tokens (
                    token_id, verified_user_id, access_token, refresh_token,
                    access_token_expires_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    access_token_expires_at = excluded.access_token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    token_id,
                    verified_user_id,
                    encrypted_access_token,
                    encrypted_refresh_token,
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
                "SELECT access_token, refresh_token, access_token_expires_at, verified_user_id "
                "FROM oauth_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "access_token": self._decrypt_token(row[0]) if isinstance(row[0], str) else None,
            "refresh_token": self._decrypt_token(row[1]) if isinstance(row[1], str) else None,
            "access_token_expires_at": row[2],
            "verified_user_id": row[3],
        }

    def get_oauth_token_by_verified_user_id(
        self,
        verified_user_id: int,
    ) -> dict[str, str | int | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_id, access_token, refresh_token, access_token_expires_at "
                "FROM oauth_tokens WHERE verified_user_id = ?",
                (verified_user_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "token_id": row[0],
            "access_token": self._decrypt_token(row[1]) if isinstance(row[1], str) else None,
            "refresh_token": self._decrypt_token(row[2]) if isinstance(row[2], str) else None,
            "access_token_expires_at": row[3],
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
                "access_token_expires_at": row[5],
                "last_sync_utc": row[6],
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
            "access_token_expires_at": row[7],
            "last_sync_utc": row[8],
            "created_at": row[9],
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
                "access_token_expires_at": row[7],
                "last_sync_utc": row[8],
                "created_at": row[9],
            }
            for row in rows
        ]
