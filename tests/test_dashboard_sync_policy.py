from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.dashboard.dashboard_ui import (
    _any_account_stale,
    _latest_sync_utc,
    _manual_sync_cooldown_remaining_seconds,
)


def test_latest_sync_utc_picks_newest_timestamp() -> None:
    accounts = [
        {"last_sync_utc": "2026-04-05T10:00:00+00:00"},
        {"last_sync_utc": "2026-04-05T11:30:00+00:00"},
        {"last_sync_utc": None},
    ]

    latest = _latest_sync_utc(accounts)

    assert latest is not None
    assert latest.isoformat() == "2026-04-05T11:30:00+00:00"


def test_any_account_stale_true_when_never_synced() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    accounts = [{"last_sync_utc": None}]

    assert _any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_any_account_stale_true_when_outside_staleness_window() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    stale_timestamp = (now_utc - timedelta(hours=25)).isoformat()
    accounts = [{"last_sync_utc": stale_timestamp}]

    assert _any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_any_account_stale_false_when_all_accounts_recent() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    recent_timestamp = (now_utc - timedelta(hours=2)).isoformat()
    accounts = [
        {"last_sync_utc": recent_timestamp},
        {"last_sync_utc": (now_utc - timedelta(hours=4)).isoformat()},
    ]

    assert not _any_account_stale(accounts, now_utc=now_utc, staleness_hours=24)


def test_manual_sync_cooldown_returns_zero_when_no_sync_exists() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)

    remaining = _manual_sync_cooldown_remaining_seconds(
        None,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 0


def test_manual_sync_cooldown_blocks_within_one_hour() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    latest_sync = now_utc - timedelta(minutes=20)

    remaining = _manual_sync_cooldown_remaining_seconds(
        latest_sync,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 2400


def test_manual_sync_cooldown_allows_after_one_hour() -> None:
    now_utc = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    latest_sync = now_utc - timedelta(hours=1, minutes=1)

    remaining = _manual_sync_cooldown_remaining_seconds(
        latest_sync,
        now_utc=now_utc,
        cooldown_seconds=3600,
    )

    assert remaining == 0
