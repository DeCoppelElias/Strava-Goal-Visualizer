"""Dashboard sync policy and orchestration service.

Handles sync eligibility checks, cooldown management, and sync execution
for both personal and club views. Separated from UI layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st

from app.services.sync import sync_verified_user_runs
from app.strava.client import StravaClientError, StravaRateLimitError


def latest_sync_utc(oauth_accounts: list[dict[str, Any]]) -> datetime | None:
    """Return the most recent sync timestamp across all OAuth accounts."""
    latest: datetime | None = None
    for account in oauth_accounts:
        last_sync = parse_last_sync_utc(account.get("last_sync_utc"))
        if last_sync is None:
            continue
        if latest is None or last_sync > latest:
            latest = last_sync
    return latest


def any_account_stale(
    oauth_accounts: list[dict[str, Any]],
    *,
    now_utc: datetime,
    staleness_hours: int,
) -> bool:
    """Check if any OAuth account's data is stale (outside sync window)."""
    if not oauth_accounts:
        return False

    stale_before = now_utc - timedelta(hours=staleness_hours)
    for account in oauth_accounts:
        last_sync = parse_last_sync_utc(account.get("last_sync_utc"))
        if last_sync is None or last_sync <= stale_before:
            return True
    return False


def manual_sync_cooldown_remaining_seconds(
    latest_sync_utc_value: datetime | None,
    *,
    now_utc: datetime,
    cooldown_seconds: int,
) -> int:
    """Calculate remaining cooldown seconds before next manual sync is allowed."""
    if latest_sync_utc_value is None:
        return 0

    elapsed_seconds = int((now_utc - latest_sync_utc_value).total_seconds())
    return max(0, cooldown_seconds - elapsed_seconds)


def account_last_sync_utc(
    oauth_accounts: list[dict[str, Any]],
    verified_user_id: int,
) -> datetime | None:
    """Retrieve last sync timestamp for a specific verified user."""
    for account in oauth_accounts:
        account_user_id = account.get("verified_user_id")
        if isinstance(account_user_id, int) and account_user_id == verified_user_id:
            return parse_last_sync_utc(account.get("last_sync_utc"))
    return None


def eligible_club_sync_user_ids(
    club_accounts: list[dict[str, Any]],
    *,
    now_utc: datetime,
    cooldown_seconds: int,
) -> tuple[list[int], int]:
    """Return (eligible_ids, skipped_cooldown_count) for club sync."""
    eligible_user_ids: list[int] = []
    skipped_cooldown_count = 0

    for account in club_accounts:
        verified_user_id = account.get("verified_user_id")
        if not isinstance(verified_user_id, int):
            continue

        last_sync_utc_val = parse_last_sync_utc(account.get("last_sync_utc"))
        remaining = manual_sync_cooldown_remaining_seconds(
            last_sync_utc_val,
            now_utc=now_utc,
            cooldown_seconds=cooldown_seconds,
        )
        if remaining > 0:
            skipped_cooldown_count += 1
            continue

        eligible_user_ids.append(verified_user_id)

    return eligible_user_ids, skipped_cooldown_count


def run_sync_for_viewer(settings: Any, *, verified_user_id: int, reason: str) -> bool:
    """Execute sync for a single verified viewer and show feedback in sidebar."""
    try:
        with st.spinner(reason):
            result = sync_verified_user_runs(settings, verified_user_id)
    except (StravaRateLimitError, StravaClientError, ValueError) as exc:
        st.sidebar.warning(f"Sync failed, showing cached data: {exc}")
        return False

    st.sidebar.success(
        "Your sync complete "
        f"(fetched {result.fetched_activities}, stored {result.stored_activities} activities)."
    )
    return True


def run_sync_for_club_members(
    settings: Any,
    *,
    club_id: int,
    club_accounts: list[dict[str, Any]],
) -> bool:
    """Execute sync for eligible club members with per-member cooldown enforcement."""
    cooldown_seconds = settings.manual_sync_cooldown_seconds
    now_utc = datetime.now(UTC)
    eligible_user_ids, skipped_cooldown_count = eligible_club_sync_user_ids(
        club_accounts,
        now_utc=now_utc,
        cooldown_seconds=cooldown_seconds,
    )

    if not eligible_user_ids:
        st.sidebar.info("All connected members in this club are in cooldown. " "Try again shortly.")
        return True

    synced_count = 0
    failed_count = 0
    total_stored_activities = 0
    with st.spinner(
        f"Syncing club {club_id} members ({len(eligible_user_ids)} eligible accounts)..."
    ):
        for verified_user_id in eligible_user_ids:
            try:
                result = sync_verified_user_runs(settings, verified_user_id)
                synced_count += 1
                total_stored_activities += result.stored_activities
            except StravaRateLimitError as exc:
                st.sidebar.warning(
                    f"Strava rate limit reached during club sync: {exc}. " "Try again later."
                )
                failed_count += 1
                break
            except (StravaClientError, ValueError) as exc:
                failed_count += 1
                st.sidebar.warning(f"Failed syncing member id={verified_user_id}: {exc}")

    st.sidebar.success(
        "Club sync complete "
        f"(synced {synced_count}, skipped cooldown {skipped_cooldown_count}, "
        f"failed {failed_count}, stored {total_stored_activities} activities)."
    )
    return True


def parse_last_sync_utc(value: Any) -> datetime | None:
    """Parse ISO-format sync timestamp, ensuring UTC timezone."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
