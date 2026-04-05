from __future__ import annotations

from pathlib import Path

import pytest

import app.services.sync as sync_module
from app.config import Settings
from app.services.sync import SyncResult, sync_all_authorized_users
from app.storage.sqlite import SQLiteRepository


def _settings(db_path: Path) -> Settings:
    return Settings(
        strava_client_id=1,
        strava_client_secret="secret",
        annual_goal_km=365.0,
        database_path=db_path,
        sync_page_size=50,
        sync_page_delay_seconds=0,
        sync_max_pages=5,
        request_timeout_seconds=20,
    )


def test_sync_all_authorized_users_no_accounts(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "cache.db")
    result = sync_all_authorized_users(settings)
    assert result.accounts_seen == 0
    assert result.accounts_synced == 0
    assert result.total_fetched_activities == 0
    assert result.total_stored_activities == 0


def test_sync_all_authorized_users_aggregates_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()
    repo.save_verified_user(1, "Jane", "Williams")
    repo.save_oauth_token("verified_1", 1, "token-1", "refresh-1", 1775300000)
    repo.save_verified_user(2, "John", "Doe")
    repo.save_oauth_token("verified_2", 2, "token-2", "refresh-2", 1775300000)

    def fake_sync_verified_user_runs(settings: Settings, verified_user_id: int) -> SyncResult:
        from datetime import UTC, datetime

        fetched = 10 if verified_user_id == 1 else 5
        stored = 8 if verified_user_id == 1 else 4
        now = datetime.now(UTC)
        return SyncResult(
            fetched_activities=fetched,
            stored_activities=stored,
            from_timestamp=now,
            to_timestamp=now,
        )

    monkeypatch.setattr(sync_module, "sync_verified_user_runs", fake_sync_verified_user_runs)

    result = sync_all_authorized_users(_settings(db_path))
    assert result.accounts_seen == 2
    assert result.accounts_synced == 2
    assert result.total_fetched_activities == 15
    assert result.total_stored_activities == 12


def test_to_club_activity_uses_verified_name_fallbacks_for_missing_names() -> None:
    payload = {
        "id": 123,
        "name": "Morning Run",
        "distance": 5000.0,
        "moving_time": 1500,
        "elapsed_time": 1600,
        "total_elevation_gain": 25.0,
        "sport_type": "Run",
        "start_date": "2026-04-05T08:00:00Z",
        "athlete": {"id": 77},
    }

    activity = sync_module._to_club_activity(payload, 77, "Jane", "Williams")

    assert activity.athlete_name == "Jane Williams"


def test_to_club_activity_keeps_payload_name_when_present() -> None:
    payload = {
        "id": 124,
        "name": "Lunch Run",
        "distance": 6000.0,
        "moving_time": 1700,
        "elapsed_time": 1800,
        "total_elevation_gain": 30.0,
        "sport_type": "Run",
        "start_date": "2026-04-05T12:00:00Z",
        "athlete": {"id": 88, "firstname": "Alex", "lastname": "Smith"},
    }

    activity = sync_module._to_club_activity(payload, 88, "Fallback", "User")

    assert activity.athlete_name == "Alex Smith"
