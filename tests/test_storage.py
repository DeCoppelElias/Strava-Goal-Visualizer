from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.storage.sqlite import SQLiteRepository
from app.strava.models import ClubActivity


def test_upsert_activities_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    activity = ClubActivity(
        activity_id=123,
        athlete_id=1,
        athlete_name="Runner",
        name="Morning Run",
        distance_m=10000.0,
        moving_time_s=2400,
        elapsed_time_s=2500,
        elevation_gain_m=120.0,
        sport_type="Run",
        start_date_utc=datetime(2026, 1, 3, tzinfo=UTC),
        raw_payload={"id": 123},
    )

    inserted_first = repo.upsert_activities([activity])
    inserted_second = repo.upsert_activities([activity])

    assert inserted_first == 1
    assert inserted_second == 1

    rows = repo.fetch_activities_df(
        start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
        end_date_utc=datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert len(rows) == 1


def test_list_activity_years_returns_descending_years(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    activities = [
        ClubActivity(
            activity_id=1,
            athlete_id=1,
            athlete_name="Runner",
            name="Run 2025",
            distance_m=5000.0,
            moving_time_s=1200,
            elapsed_time_s=1300,
            elevation_gain_m=20.0,
            sport_type="Run",
            start_date_utc=datetime(2025, 6, 1, tzinfo=UTC),
            raw_payload={"id": 1},
        ),
        ClubActivity(
            activity_id=2,
            athlete_id=1,
            athlete_name="Runner",
            name="Run 2026",
            distance_m=7000.0,
            moving_time_s=1600,
            elapsed_time_s=1700,
            elevation_gain_m=35.0,
            sport_type="Run",
            start_date_utc=datetime(2026, 2, 1, tzinfo=UTC),
            raw_payload={"id": 2},
        ),
    ]
    repo.upsert_activities(activities)

    years = repo.list_activity_years()

    assert years == [2026, 2025]


def test_export_verified_user_data_returns_user_token_and_activities(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(42, "Jane", "Williams", email="jane@example.com")
    repo.save_oauth_token("verified_42", 42, "token", "refresh", 1775300000)
    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=99,
                athlete_id=42,
                athlete_name="Jane Williams",
                name="Morning Run",
                distance_m=10000.0,
                moving_time_s=2000,
                elapsed_time_s=2100,
                elevation_gain_m=100.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
                raw_payload={"id": 99},
            )
        ]
    )

    exported = repo.export_verified_user_data(42)

    assert exported is not None
    assert exported["verified_user"]["verified_user_id"] == 42
    assert len(exported["oauth_tokens"]) == 1
    assert len(exported["activities"]) == 1
    assert exported["activities"][0]["activity_id"] == 99


def test_list_inactive_oauth_accounts_uses_last_sync_or_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(1, "Old", "Runner")
    repo.save_oauth_token("verified_1", 1, "token1", "refresh1", 1775300000)
    repo.set_oauth_last_sync_utc("verified_1", datetime.now(UTC) - timedelta(days=60))

    repo.save_verified_user(2, "Recent", "Runner")
    repo.save_oauth_token("verified_2", 2, "token2", "refresh2", 1775300000)
    repo.set_oauth_last_sync_utc("verified_2", datetime.now(UTC))

    cutoff = datetime.now(UTC) - timedelta(days=30)
    inactive = repo.list_inactive_oauth_accounts(cutoff)
    inactive_ids = {int(item["verified_user_id"]) for item in inactive}

    assert 1 in inactive_ids
    assert 2 not in inactive_ids


def test_delete_verified_user_data_removes_related_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(88, "Alex", "Doe")
    repo.save_oauth_token("verified_88", 88, "token", "refresh", 1775300000)
    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=100,
                athlete_id=88,
                athlete_name="Alex Doe",
                name="Evening Run",
                distance_m=7000.0,
                moving_time_s=1800,
                elapsed_time_s=1900,
                elevation_gain_m=45.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 2, 1, tzinfo=UTC),
                raw_payload={"id": 100},
            )
        ]
    )

    deleted = repo.delete_verified_user_data(88, delete_activities=True)

    assert deleted["verified_users"] == 1
    assert deleted["oauth_tokens"] == 1
    assert deleted["activities"] == 1

    conn = sqlite3.connect(db_path)
    user_row = conn.execute(
        "SELECT 1 FROM verified_users WHERE verified_user_id = ?",
        (88,),
    ).fetchone()
    token_row = conn.execute(
        "SELECT 1 FROM oauth_tokens WHERE verified_user_id = ?",
        (88,),
    ).fetchone()
    activity_row = conn.execute(
        "SELECT 1 FROM activities WHERE athlete_id = ?",
        (88,),
    ).fetchone()
    conn.close()

    assert user_row is None
    assert token_row is None
    assert activity_row is None


def test_dsar_audit_log_records_and_reads_events(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(101, "Casey", "Runner")
    repo.log_dsar_event(
        verified_user_id=101,
        event_type="export",
        request_source="dashboard",
        details={"result": "downloaded"},
    )
    repo.log_dsar_event(
        verified_user_id=101,
        event_type="erasure",
        request_source="cli",
        details={"result": "completed", "deleted": {"activities": 3}},
    )

    events = repo.list_dsar_events()

    assert len(events) == 2
    assert events[0]["event_type"] == "export"
    assert events[0]["request_source"] == "dashboard"
    assert events[0]["details"] == {"result": "downloaded"}
    assert events[1]["event_type"] == "erasure"
    assert events[1]["details"] == {
        "result": "completed",
        "deleted": {"activities": 3},
    }


def test_delete_verified_user_data_keeps_dsar_events_without_fk_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(202, "Jordan", "Runner")
    repo.save_oauth_token("verified_202", 202, "token", "refresh", 1775300000)
    repo.log_dsar_event(
        verified_user_id=202,
        event_type="erasure",
        request_source="dashboard",
        details={"result": "requested"},
    )

    deleted = repo.delete_verified_user_data(202, delete_activities=True)

    assert deleted["verified_users"] == 1

    events = repo.list_dsar_events()
    assert len(events) == 1
    assert events[0]["verified_user_id"] is None


def test_post_delete_erasure_completed_event_uses_null_fk(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(303, "Taylor", "Runner")
    repo.log_dsar_event(
        verified_user_id=303,
        event_type="erasure",
        request_source="dashboard",
        details={"result": "requested"},
    )
    deleted = repo.delete_verified_user_data(303, delete_activities=True)

    repo.log_dsar_event(
        verified_user_id=None,
        event_type="erasure",
        request_source="dashboard",
        details={
            "result": "completed",
            "deleted": deleted,
            "deleted_verified_user_id": 303,
        },
    )

    events = repo.list_dsar_events()
    assert len(events) == 2
    assert events[0]["event_type"] == "erasure"
    assert events[0]["verified_user_id"] is None
    assert events[0]["details"] == {"result": "requested"}
    assert events[1]["event_type"] == "erasure"
    assert events[1]["verified_user_id"] is None
    assert events[1]["details"] == {
        "result": "completed",
        "deleted": deleted,
        "deleted_verified_user_id": 303,
    }


def test_delete_verified_user_data_removes_club_and_identity_link_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(707, "Mila", "Runner")
    repo.save_oauth_token("verified_707", 707, "token", "refresh", 1775300000)
    repo.replace_verified_user_clubs(707, [44, 55])
    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=701,
                athlete_id=707,
                athlete_name="Mila Runner",
                name="Club Run",
                distance_m=9000.0,
                moving_time_s=2400,
                elapsed_time_s=2500,
                elevation_gain_m=110.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 4, 1, tzinfo=UTC),
                raw_payload={"id": 701},
            )
        ]
    )
    repo.save_identity_link(
        club_athlete_id=707,
        verified_user_id=707,
        confidence=1.0,
        match_type="exact",
    )

    deleted = repo.delete_verified_user_data(707, delete_activities=True)

    assert deleted["verified_users"] == 1

    conn = sqlite3.connect(db_path)
    link_row = conn.execute(
        "SELECT 1 FROM athlete_identity_links WHERE verified_user_id = ? OR club_athlete_id = ?",
        (707, 707),
    ).fetchone()
    club_row = conn.execute(
        "SELECT 1 FROM verified_user_clubs WHERE verified_user_id = ?",
        (707,),
    ).fetchone()
    conn.close()

    assert link_row is None
    assert club_row is None


def test_verified_user_club_membership_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(404, "Riley", "Runner")
    repo.replace_verified_user_clubs(404, [10, 20, 20])

    assert repo.list_verified_user_club_ids(404) == [10, 20]
    assert repo.is_verified_user_in_club(404, 10)
    assert not repo.is_verified_user_in_club(404, 99)


def test_fetch_activities_df_can_scope_to_verified_user(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=501,
                athlete_id=1,
                athlete_name="Runner One",
                name="Run One",
                distance_m=5000.0,
                moving_time_s=1400,
                elapsed_time_s=1500,
                elevation_gain_m=25.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
                raw_payload={"id": 501},
            ),
            ClubActivity(
                activity_id=502,
                athlete_id=2,
                athlete_name="Runner Two",
                name="Run Two",
                distance_m=6000.0,
                moving_time_s=1500,
                elapsed_time_s=1600,
                elevation_gain_m=30.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 1, 2, tzinfo=UTC),
                raw_payload={"id": 502},
            ),
        ]
    )

    scoped = repo.fetch_activities_df(
        start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
        end_date_utc=datetime(2026, 12, 31, tzinfo=UTC),
        verified_user_id=1,
    )

    assert len(scoped) == 1
    assert int(scoped.iloc[0]["athlete_id"]) == 1


def test_fetch_activities_df_can_scope_to_authorized_club_members(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    for verified_user_id, first in [(11, "Ava"), (22, "Ben"), (33, "Cam")]:
        repo.save_verified_user(verified_user_id, first, "Runner")
        repo.save_oauth_token(
            token_id=f"verified_{verified_user_id}",
            verified_user_id=verified_user_id,
            access_token="token",
            refresh_token="refresh",
            access_token_expires_at=1775300000,
        )

    repo.replace_verified_user_clubs(11, [77])
    repo.replace_verified_user_clubs(22, [77])
    repo.replace_verified_user_clubs(33, [88])

    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=611,
                athlete_id=11,
                athlete_name="Ava Runner",
                name="Ava Run",
                distance_m=5100.0,
                moving_time_s=1300,
                elapsed_time_s=1400,
                elevation_gain_m=20.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 3, 1, tzinfo=UTC),
                raw_payload={"id": 611},
            ),
            ClubActivity(
                activity_id=622,
                athlete_id=22,
                athlete_name="Ben Runner",
                name="Ben Run",
                distance_m=6200.0,
                moving_time_s=1500,
                elapsed_time_s=1600,
                elevation_gain_m=35.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 3, 2, tzinfo=UTC),
                raw_payload={"id": 622},
            ),
            ClubActivity(
                activity_id=633,
                athlete_id=33,
                athlete_name="Cam Runner",
                name="Cam Run",
                distance_m=7300.0,
                moving_time_s=1700,
                elapsed_time_s=1800,
                elevation_gain_m=40.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 3, 3, tzinfo=UTC),
                raw_payload={"id": 633},
            ),
        ]
    )

    club_scoped = repo.fetch_activities_df(
        start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
        end_date_utc=datetime(2026, 12, 31, tzinfo=UTC),
        club_id=77,
    )

    athlete_ids = {int(value) for value in club_scoped["athlete_id"].tolist()}
    assert athlete_ids == {11, 22}


def test_user_annual_goal_defaults_and_persists_update(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(808, "Nova", "Runner")

    default_goal = repo.get_user_annual_goal(808)
    assert default_goal == 365.0

    repo.update_user_annual_goal(808, 500.0)
    updated_goal = repo.get_user_annual_goal(808)
    assert updated_goal == 500.0


def test_get_user_annual_goals_uses_defaults_for_missing_values(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(901, "Kai", "Runner")
    repo.save_verified_user(902, "Lee", "Runner")
    repo.update_user_annual_goal(901, 450.0)

    goal_map = repo.get_user_annual_goals([901, 902, 903])

    assert goal_map[901] == 450.0
    assert goal_map[902] == 365.0
    assert goal_map[903] == 365.0


def test_export_verified_user_data_includes_annual_goal(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(444, "Goal", "Runner")
    repo.update_user_annual_goal(444, 420.0)

    exported = repo.export_verified_user_data(444)

    assert exported is not None
    assert float(exported["verified_user"]["annual_goal_km"]) == 420.0


def test_delete_verified_user_data_removes_annual_goal_with_user_row(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(555, "Delete", "Runner")
    repo.update_user_annual_goal(555, 610.0)

    deleted = repo.delete_verified_user_data(555, delete_activities=True)

    assert deleted["verified_users"] == 1
    assert repo.export_verified_user_data(555) is None


def test_update_user_annual_goal_rejects_above_max(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(777, "Cap", "Runner")

    with pytest.raises(ValueError, match="must be <="):
        repo.update_user_annual_goal(777, 100001.0, max_annual_goal_km=100000.0)


def test_count_activities_older_than_respects_cutoff(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=1001,
                athlete_id=1,
                athlete_name="Runner One",
                name="Old Run",
                distance_m=5000.0,
                moving_time_s=1400,
                elapsed_time_s=1500,
                elevation_gain_m=25.0,
                sport_type="Run",
                start_date_utc=datetime(2022, 1, 1, tzinfo=UTC),
                raw_payload={"id": 1001},
            ),
            ClubActivity(
                activity_id=1002,
                athlete_id=1,
                athlete_name="Runner One",
                name="Recent Run",
                distance_m=6000.0,
                moving_time_s=1500,
                elapsed_time_s=1600,
                elevation_gain_m=30.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
                raw_payload={"id": 1002},
            ),
        ]
    )

    count = repo.count_activities_older_than(datetime(2024, 1, 1, tzinfo=UTC))

    assert count == 1


def test_delete_activities_older_than_deletes_old_and_orphan_athletes(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(100, "Old", "Athlete")
    repo.save_verified_user(200, "New", "Athlete")
    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=2001,
                athlete_id=100,
                athlete_name="Old Athlete",
                name="Old Run",
                distance_m=5000.0,
                moving_time_s=1400,
                elapsed_time_s=1500,
                elevation_gain_m=25.0,
                sport_type="Run",
                start_date_utc=datetime(2021, 1, 1, tzinfo=UTC),
                raw_payload={"id": 2001},
            ),
            ClubActivity(
                activity_id=2002,
                athlete_id=200,
                athlete_name="New Athlete",
                name="Recent Run",
                distance_m=6000.0,
                moving_time_s=1500,
                elapsed_time_s=1600,
                elevation_gain_m=30.0,
                sport_type="Run",
                start_date_utc=datetime(2026, 1, 1, tzinfo=UTC),
                raw_payload={"id": 2002},
            ),
        ]
    )

    deleted = repo.delete_activities_older_than(datetime(2024, 1, 1, tzinfo=UTC))

    assert deleted == {"activities": 1, "athletes": 1}

    remaining = repo.fetch_activities_df(
        start_date_utc=datetime(2020, 1, 1, tzinfo=UTC),
        end_date_utc=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert len(remaining) == 1
    assert int(remaining.iloc[0]["activity_id"]) == 2002


def test_delete_activities_older_than_keeps_athlete_with_identity_link(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.db"
    repo = SQLiteRepository(db_path)
    repo.initialize()

    repo.save_verified_user(300, "Linked", "Athlete")
    repo.upsert_activities(
        [
            ClubActivity(
                activity_id=3001,
                athlete_id=300,
                athlete_name="Linked Athlete",
                name="Very Old Run",
                distance_m=5000.0,
                moving_time_s=1400,
                elapsed_time_s=1500,
                elevation_gain_m=25.0,
                sport_type="Run",
                start_date_utc=datetime(2020, 1, 1, tzinfo=UTC),
                raw_payload={"id": 3001},
            )
        ]
    )
    repo.save_identity_link(
        club_athlete_id=300,
        verified_user_id=300,
        confidence=0.99,
        match_type="name_match",
    )

    deleted = repo.delete_activities_older_than(datetime(2024, 1, 1, tzinfo=UTC))

    assert deleted == {"activities": 1, "athletes": 0}
    athletes = repo.list_athletes()
    athlete_ids = {int(item["athlete_id"]) for item in athletes}
    assert 300 in athlete_ids
