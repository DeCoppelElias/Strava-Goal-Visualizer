from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.dashboard_sync import (
    any_account_stale,
    eligible_club_sync_user_ids,
    latest_sync_utc,
    manual_sync_cooldown_remaining_seconds,
    parse_last_sync_utc,
)


def test_latest_sync_utc_picks_newest_timestamp() -> None:
    accounts = [
        {"last_sync_utc": "2026-04-05T10:00:00+00:00"},
        {"last_sync_utc": "2026-04-05T11:30:00+00:00"},
        {"last_sync_utc": None},
    ]

    latest = latest_sync_utc(accounts)

    assert latest is not None
    assert latest.isoformat() == "2026-04-05T11:30:00+00:00"


def test_any_account_stale_true_when_never_synced() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    accounts = [{"last_sync_utc": None}]

    assert any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_any_account_stale_true_when_outside_staleness_window() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    stale_timestamp = (now_utc - timedelta(hours=25)).isoformat()
    accounts = [{"last_sync_utc": stale_timestamp}]

    assert any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_any_account_stale_false_when_all_accounts_recent() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    recent_timestamp = (now_utc - timedelta(hours=2)).isoformat()
    accounts = [
        {"last_sync_utc": recent_timestamp},
        {"last_sync_utc": (now_utc - timedelta(hours=4)).isoformat()},
    ]

    assert not any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_manual_sync_cooldown_returns_zero_when_no_sync_exists() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)

    remaining = manual_sync_cooldown_remaining_seconds(
        None,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 0


def test_manual_sync_cooldown_blocks_within_one_hour() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    latest_sync = now_utc - timedelta(minutes=20)

    remaining = manual_sync_cooldown_remaining_seconds(
        latest_sync,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 2400


def test_manual_sync_cooldown_allows_after_one_hour() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    latest_sync = now_utc - timedelta(hours=1, minutes=1)

    remaining = manual_sync_cooldown_remaining_seconds(
        latest_sync,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 0


def test_parse_last_sync_utc_handles_naive_and_aware_inputs() -> None:
    naive = parse_last_sync_utc("2026-04-05T11:30:00")
    aware = parse_last_sync_utc("2026-04-05T11:30:00+00:00")

    assert naive is not None
    assert aware is not None
    assert naive.isoformat() == "2026-04-05T11:30:00+00:00"
    assert aware.isoformat() == "2026-04-05T11:30:00+00:00"


def test_parse_last_sync_utc_returns_none_for_invalid_values() -> None:
    assert parse_last_sync_utc(None) is None
    assert parse_last_sync_utc(123) is None
    assert parse_last_sync_utc("not-a-date") is None


def test_eligible_club_sync_user_ids_filters_by_per_member_cooldown() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    cooldown_seconds = 3600
    club_accounts = [
        {"verified_user_id": 1, "last_sync_utc": (now_utc - timedelta(hours=2)).isoformat()},
        {"verified_user_id": 2, "last_sync_utc": (now_utc - timedelta(minutes=10)).isoformat()},
        {"verified_user_id": 3, "last_sync_utc": None},
        {"verified_user_id": "bad", "last_sync_utc": None},
    ]

    eligible_ids, skipped_count = eligible_club_sync_user_ids(
        club_accounts,
        now_utc=now_utc,
        cooldown_seconds=cooldown_seconds,
    )

    assert eligible_ids == [1, 3]
    assert skipped_count == 1
