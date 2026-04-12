"""Tests for OAuth flow and name matching utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.strava.models import canonical_athlete_name
from app.strava.oauth import (
    StravaOAuthError,
    build_authorize_url,
    exchange_code_for_tokens,
)


class TestBuildAuthorizeUrl:
    """Tests for OAuth authorize URL generation."""

    def test_build_authorize_url_includes_required_params(self) -> None:
        """Authorize URL should include all required OAuth 2.0 parameters."""
        url = build_authorize_url(client_id=12345)

        assert "https://www.strava.com/oauth/authorize?" in url
        assert "client_id=12345" in url
        assert "response_type=code" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url
        assert "scope=activity%3Aread_all%2Cprofile%3Aread_all" in url
        assert "approval_prompt=force" in url

    def test_build_authorize_url_custom_redirect(self) -> None:
        """Should accept custom redirect_uri."""
        url = build_authorize_url(
            client_id=12345,
            redirect_uri="https://example.com/auth/callback",
        )

        assert "redirect_uri=https%3A%2F%2Fexample.com%2Fauth%2Fcallback" in url

    def test_build_authorize_url_custom_scope(self) -> None:
        """Should accept custom scope."""
        url = build_authorize_url(
            client_id=12345,
            scope="activity:read",
        )

        assert "scope=activity%3Aread" in url


class TestExchangeCodeForTokens:
    """Tests for OAuth token exchange."""

    def test_exchange_code_success(self) -> None:
        """Should parse successful token response."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token_type": "Bearer",
            "expires_at": 1712280000,
            "expires_in": 21600,
            "refresh_token": "refresh_abc123",
            "access_token": "access_xyz789",
        }

        with patch("requests.post", return_value=mock_response):
            result = exchange_code_for_tokens(
                code="auth_code_123",
                client_id=12345,
                client_secret="client_secret_xyz",
            )

        assert result["access_token"] == "access_xyz789"
        assert result["refresh_token"] == "refresh_abc123"
        assert result["expires_at"] == 1712280000

    def test_exchange_code_http_error(self) -> None:
        """Should raise StravaOAuthError on HTTP error."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(StravaOAuthError, match="token exchange failed"):
                exchange_code_for_tokens(
                    code="invalid_code",
                    client_id=12345,
                    client_secret="secret",
                )

    def test_exchange_code_missing_access_token(self) -> None:
        """Should raise StravaOAuthError if access_token missing."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "expires_at": 1712280000,
            "refresh_token": "refresh_abc",
        }

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(StravaOAuthError, match="Missing access_token"):
                exchange_code_for_tokens(
                    code="auth_code",
                    client_id=12345,
                    client_secret="secret",
                )

    def test_exchange_code_missing_expires_at(self) -> None:
        """Should raise StravaOAuthError if expires_at missing."""
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "token_abc",
            "refresh_token": "refresh_xyz",
        }

        with patch("requests.post", return_value=mock_response):
            with pytest.raises(StravaOAuthError, match="expires_at"):
                exchange_code_for_tokens(
                    code="auth_code",
                    client_id=12345,
                    client_secret="secret",
                )

    def test_exchange_code_network_error(self) -> None:
        """Should raise StravaOAuthError on network error."""
        with patch("requests.post", side_effect=requests.ConnectionError("Network error")):
            with pytest.raises(StravaOAuthError, match="reach Strava"):
                exchange_code_for_tokens(
                    code="auth_code",
                    client_id=12345,
                    client_secret="secret",
                )


class TestCanonicalAthleteName:
    """Tests for athlete name canonicalization."""

    def test_canonical_name_exact_match(self) -> None:
        """Should normalize to lowercase, space-separated."""
        assert canonical_athlete_name("Jane", "Williams") == "jane williams"

    def test_canonical_name_whitespace_stripped(self) -> None:
        """Should strip leading/trailing whitespace."""
        assert canonical_athlete_name("  Jane  ", "  Williams  ") == "jane williams"

    def test_canonical_name_multiple_spaces(self) -> None:
        """Should collapse multiple spaces."""
        assert canonical_athlete_name("Jane Marie", "Williams") == "jane marie williams"

    def test_canonical_name_missing_first(self) -> None:
        """Should handle missing first name."""
        assert canonical_athlete_name(None, "Williams") == "williams"

    def test_canonical_name_missing_last(self) -> None:
        """Should handle missing last name."""
        assert canonical_athlete_name("Jane", None) == "jane"

    def test_canonical_name_both_missing(self) -> None:
        """Should return 'unknown' when both names missing."""
        assert canonical_athlete_name(None, None) == "unknown"
        assert canonical_athlete_name("", "") == "unknown"


class TestPendingOAuthState:
    """Tests for short-lived OAuth state persistence used by web redirect flow."""

    def test_consume_valid_state_returns_true(self, tmp_path: Path) -> None:
        from app.storage.sqlite import SQLiteRepository

        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()
        repo.save_pending_oauth_state("abc123", ttl_seconds=60)
        assert repo.consume_pending_oauth_state("abc123") is True

    def test_consume_unknown_state_returns_false(self, tmp_path: Path) -> None:
        from app.storage.sqlite import SQLiteRepository

        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()
        assert repo.consume_pending_oauth_state("not-saved") is False

    def test_consume_state_is_single_use(self, tmp_path: Path) -> None:
        from app.storage.sqlite import SQLiteRepository

        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()
        repo.save_pending_oauth_state("xyz", ttl_seconds=60)
        assert repo.consume_pending_oauth_state("xyz") is True
        assert repo.consume_pending_oauth_state("xyz") is False

    def test_consume_expired_state_returns_false(self, tmp_path: Path) -> None:
        import sqlite3
        from datetime import UTC, datetime, timedelta

        from app.storage.sqlite import SQLiteRepository

        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()
        # Insert already-expired state directly
        past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        conn = sqlite3.connect(tmp_path / "cache.db")
        conn.execute(
            "INSERT INTO oauth_pending_states (state, expires_at, created_at) VALUES (?, ?, ?)",
            ("expired", past, past),
        )
        conn.commit()
        conn.close()
        assert repo.consume_pending_oauth_state("expired") is False

    def test_purge_removes_only_expired(self, tmp_path: Path) -> None:
        import sqlite3
        from datetime import UTC, datetime, timedelta

        from app.storage.sqlite import SQLiteRepository

        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()
        repo.save_pending_oauth_state("fresh", ttl_seconds=600)
        past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        conn = sqlite3.connect(tmp_path / "cache.db")
        conn.execute(
            "INSERT INTO oauth_pending_states (state, expires_at, created_at) VALUES (?, ?, ?)",
            ("stale", past, past),
        )
        conn.commit()
        conn.close()

        repo.purge_expired_oauth_states()

        assert repo.consume_pending_oauth_state("fresh") is True
        assert repo.consume_pending_oauth_state("stale") is False


class TestBeginCompleteOAuthFlow:
    """Tests for web OAuth redirect flow helpers."""

    def test_begin_oauth_flow_raises_without_app_base_url(self, tmp_path: Path) -> None:
        from app.config import Settings
        from app.services.oauth_auth import begin_oauth_flow
        from app.storage.sqlite import SQLiteRepository

        settings = Settings(strava_client_id=1, strava_client_secret="s", app_base_url="")
        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()

        with pytest.raises(ValueError, match="APP_BASE_URL"):
            begin_oauth_flow(settings, repo)

    def test_begin_oauth_flow_returns_strava_url_and_saves_state(self, tmp_path: Path) -> None:
        from app.config import Settings
        from app.services.oauth_auth import begin_oauth_flow
        from app.storage.sqlite import SQLiteRepository

        settings = Settings(
            strava_client_id=42,
            strava_client_secret="secret",
            app_base_url="https://example.onrender.com",
        )
        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()

        url = begin_oauth_flow(settings, repo)

        assert "strava.com/oauth/authorize" in url
        assert "client_id=42" in url
        assert "redirect_uri=https%3A%2F%2Fexample.onrender.com" in url
        assert "state=" in url

    def test_complete_oauth_flow_raises_on_invalid_state(self, tmp_path: Path) -> None:
        from app.config import Settings
        from app.services.oauth_auth import complete_oauth_flow
        from app.storage.sqlite import SQLiteRepository
        from app.strava.oauth import StravaOAuthError

        settings = Settings(
            strava_client_id=1,
            strava_client_secret="s",
            app_base_url="https://example.onrender.com",
        )
        repo = SQLiteRepository(tmp_path / "cache.db")
        repo.initialize()

        with pytest.raises(StravaOAuthError, match="Invalid or expired"):
            complete_oauth_flow(settings, repo, code="some-code", state="never-saved")
