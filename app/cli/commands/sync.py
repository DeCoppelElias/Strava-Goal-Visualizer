from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.cli.context import CommandContext
from app.services.sync import sync_all_authorized_users, sync_verified_user_runs
from app.strava.client import StravaClientError, StravaRateLimitError

logger = logging.getLogger(__name__)


def sync_command(ctx: CommandContext) -> int:
    verified_user_id = getattr(ctx.args, "verified_user_id", None)
    if verified_user_id is None:
        print(
            "Sync now requires OAuth-authorized users. "
            "Use --verified-user-id <id> for one user, or use 'sync-authorized' "
            "to sync all connected accounts."
        )
        return 1

    sync_target = f"verified_user_id={verified_user_id}"
    logger.info("Starting sync for %s", sync_target)

    try:
        result = sync_verified_user_runs(ctx.settings, verified_user_id)
        print(
            "Sync complete. "
            f"Fetched {result.fetched_activities} activities, "
            f"stored {result.stored_activities} run activities. "
            f"Window: {result.from_timestamp.isoformat()} -> {result.to_timestamp.isoformat()}."
        )
        return 0
    except StravaRateLimitError as exc:
        print("Sync paused: Strava API rate limit exceeded.")
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
            print(
                f"Retry in about {exc.retry_after_seconds} seconds "
                f"(around {retry_at.strftime('%Y-%m-%d %H:%M:%S UTC')})."
            )
        print(f"Details: {exc}")
        return 2
    except (StravaClientError, ValueError) as exc:
        print(f"Sync failed: {exc}")
        return 1


def sync_authorized_command(ctx: CommandContext) -> int:
    logger.info("Starting sync for all OAuth-authorized users")
    try:
        result = sync_all_authorized_users(ctx.settings)
    except (StravaRateLimitError, StravaClientError, ValueError) as exc:
        print(f"Authorized sync failed: {exc}")
        return 1

    if result.accounts_seen == 0:
        print("No OAuth accounts found. Run 'oauth-authorize' first.")
        return 0

    print(
        "Authorized sync complete. "
        f"Accounts seen: {result.accounts_seen}, synced: {result.accounts_synced}. "
        f"Fetched {result.total_fetched_activities} activities, "
        f"stored {result.total_stored_activities} run activities."
    )
    return 0
