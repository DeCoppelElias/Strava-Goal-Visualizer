"""Tests for OAuth token persistence and activity merging."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

from app.storage.sqlite import SQLiteRepository


class TestOAuthTokenPersistence:
    """Tests for saving and retrieving OAuth tokens from database."""

    def _seed_verified_user(self, repo: SQLiteRepository, verified_user_id: int) -> None:
        repo.save_verified_user(
            verified_user_id=verified_user_id,
            firstname=f"User{verified_user_id}",
            lastname="Test",
        )

    def test_save_oauth_token(self, tmp_path: Path) -> None:
        """Should save OAuth token to database."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 123)

        repo.save_oauth_token(
            token_id="oauth_2024_1",
            verified_user_id=123,
            access_token="access_token_abc",
            refresh_token="refresh_token_xyz",
            access_token_expires_at=1712280000,
        )

        # Retrieve and verify
        token = repo.get_oauth_token("oauth_2024_1")
        assert token is not None
        assert token["access_token"] == "access_token_abc"
        assert token["refresh_token"] == "refresh_token_xyz"
        assert token["verified_user_id"] == 123
        assert token["access_token_expires_at"] == 1712280000

    def test_save_oauth_token_no_refresh_token(self, tmp_path: Path) -> None:
        """Should handle tokens without refresh_token."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 456)

        repo.save_oauth_token(
            token_id="oauth_static",
            verified_user_id=456,
            access_token="access_only",
            refresh_token=None,
            access_token_expires_at=1712280000,
        )

        token = repo.get_oauth_token("oauth_static")
        assert token is not None
        assert token["access_token"] == "access_only"
        assert token["refresh_token"] is None

    def test_get_oauth_token_nonexistent(self, tmp_path: Path) -> None:
        """Should return None for nonexistent token."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()

        assert repo.get_oauth_token("nonexistent") is None

    def test_get_oauth_tokens_list(self, tmp_path: Path) -> None:
        """Should list all OAuth tokens."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 100)
        self._seed_verified_user(repo, 200)

        repo.save_oauth_token(
            token_id="oauth_1",
            verified_user_id=100,
            access_token="token1",
            refresh_token="refresh1",
            access_token_expires_at=1712280000,
        )
        repo.save_oauth_token(
            token_id="oauth_2",
            verified_user_id=200,
            access_token="token2",
            refresh_token="refresh2",
            access_token_expires_at=1712290000,
        )

        tokens = repo.get_oauth_tokens()
        assert len(tokens) == 2
        token_ids = {t["token_id"] for t in tokens}
        assert token_ids == {"oauth_1", "oauth_2"}

    def test_save_oauth_token_update_existing(self, tmp_path: Path) -> None:
        """Should update existing token on conflict."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 100)

        # Save token first time
        repo.save_oauth_token(
            token_id="oauth_1",
            verified_user_id=100,
            access_token="old_token",
            refresh_token="old_refresh",
            access_token_expires_at=1712280000,
        )

        # Update same token
        repo.save_oauth_token(
            token_id="oauth_1",
            verified_user_id=100,
            access_token="new_token",
            refresh_token="new_refresh",
            access_token_expires_at=1712290000,
        )

        token = repo.get_oauth_token("oauth_1")
        assert token is not None
        assert token["access_token"] == "new_token"
        assert token["refresh_token"] == "new_refresh"
        assert token["access_token_expires_at"] == 1712290000

    def test_get_oauth_token_by_verified_user_id(self, tmp_path: Path) -> None:
        """Should retrieve token by verified user id."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 77)

        repo.save_oauth_token(
            token_id="oauth_77",
            verified_user_id=77,
            access_token="token_77",
            refresh_token="refresh_77",
            access_token_expires_at=1712280000,
        )

        token = repo.get_oauth_token_by_verified_user_id(77)
        assert token is not None
        assert token["token_id"] == "oauth_77"
        assert token["access_token"] == "token_77"
        assert token["verified_user_id"] == 77

    def test_set_oauth_last_sync_utc(self, tmp_path: Path) -> None:
        """Should update oauth last_sync_utc timestamp."""
        from datetime import UTC, datetime

        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()
        self._seed_verified_user(repo, 88)

        repo.save_oauth_token(
            token_id="oauth_last_sync",
            verified_user_id=88,
            access_token="token_88",
            refresh_token=None,
            access_token_expires_at=1712280000,
        )
        now_utc = datetime.now(UTC)
        repo.set_oauth_last_sync_utc("oauth_last_sync", now_utc)

        tokens = repo.get_oauth_tokens()
        token = next(t for t in tokens if t["token_id"] == "oauth_last_sync")
        assert token["last_sync_utc"] is not None

    def test_tokens_are_encrypted_at_rest_when_key_configured(self, tmp_path: Path) -> None:
        """Should store encrypted OAuth secrets and decrypt on read."""
        db_path = tmp_path / "test.db"
        encryption_key = Fernet.generate_key().decode("utf-8")
        repo = SQLiteRepository(db_path, token_encryption_key=encryption_key)
        repo.initialize()
        self._seed_verified_user(repo, 999)

        repo.save_oauth_token(
            token_id="oauth_enc",
            verified_user_id=999,
            access_token="plain_access",
            refresh_token="plain_refresh",
            access_token_expires_at=1712280000,
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT access_token, refresh_token FROM oauth_tokens WHERE token_id = ?",
            ("oauth_enc",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] != "plain_access"
        assert row[1] != "plain_refresh"
        assert str(row[0]).startswith("enc:v1:")
        assert str(row[1]).startswith("enc:v1:")

        token = repo.get_oauth_token("oauth_enc")
        assert token is not None
        assert token["access_token"] == "plain_access"
        assert token["refresh_token"] == "plain_refresh"


class TestVerifiedUserPersistence:
    """Tests for saving and retrieving verified user profiles."""

    def test_save_verified_user(self, tmp_path: Path) -> None:
        """Should save verified user profile to database."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()

        repo.save_verified_user(
            verified_user_id=123,
            firstname="Jane",
            lastname="Williams",
            email="jane@example.com",
        )

        # Verify by querying directly (no retrieval method yet)
        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT firstname, lastname, canonical_name, email "
            "FROM verified_users WHERE verified_user_id = ?",
            (123,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "Jane"
        assert row[1] == "Williams"
        assert row[2] == "jane williams"
        assert row[3] == "jane@example.com"

    def test_save_verified_user_no_email(self, tmp_path: Path) -> None:
        """Should handle verified users without email."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()

        repo.save_verified_user(
            verified_user_id=456,
            firstname="John",
            lastname="Doe",
        )

        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT canonical_name, email FROM verified_users WHERE verified_user_id = ?",
            (456,),
        ).fetchone()
        conn.close()

        assert row[0] == "john doe"
        assert row[1] is None

    def test_save_verified_user_update_existing(self, tmp_path: Path) -> None:
        """Should update existing verified user on conflict."""
        db_path = tmp_path / "test.db"
        repo = SQLiteRepository(db_path)
        repo.initialize()

        # Save user first time
        repo.save_verified_user(
            verified_user_id=100,
            firstname="Jane",
            lastname="Williams",
            email="jane_old@example.com",
        )

        # Update same user (name change)
        repo.save_verified_user(
            verified_user_id=100,
            firstname="Jane",
            lastname="Smith",
            email="jane_new@example.com",
        )

        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT firstname, lastname, canonical_name, email "
            "FROM verified_users WHERE verified_user_id = ?",
            (100,),
        ).fetchone()
        conn.close()

        assert row[0] == "Jane"
        assert row[1] == "Smith"
        assert row[2] == "jane smith"
        assert row[3] == "jane_new@example.com"
