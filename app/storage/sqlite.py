from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.sqlite_activity import SQLiteActivityMixin
from app.storage.sqlite_oauth import SQLiteOAuthMixin
from app.storage.sqlite_privacy import SQLitePrivacyMixin
from app.storage.sqlite_schema import SQLiteSchemaMixin
from app.storage.sqlite_user import SQLiteUserMixin
from app.storage.token_encryption import TokenEncryption


class SQLiteRepository(
    SQLiteSchemaMixin,
    SQLiteActivityMixin,
    SQLiteUserMixin,
    SQLiteOAuthMixin,
    SQLitePrivacyMixin,
):
    def __init__(self, db_path: Path, token_encryption_key: str | None = None) -> None:
        self._db_path = db_path
        self._token_encryption = TokenEncryption(token_encryption_key)

    def _encrypt_token(self, token: str | None) -> str | None:
        return self._token_encryption.encrypt(token)

    def _decrypt_token(self, token: str | None) -> str | None:
        return self._token_encryption.decrypt(token)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn
