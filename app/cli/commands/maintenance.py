from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.cli.context import CommandContext
from app.services.account_lifecycle import revoke_account_if_requested


def cleanup_inactive_command(ctx: CommandContext) -> int:
    days = ctx.args.days
    execute = ctx.args.execute
    revoke = ctx.args.revoke

    if days < 1:
        print("--days must be >= 1")
        return 1

    cutoff = datetime.now(UTC) - timedelta(days=days)
    inactive_accounts = ctx.repository.list_inactive_oauth_accounts(cutoff)

    if not inactive_accounts:
        print(f"No inactive OAuth accounts found for cutoff={cutoff.isoformat()}.")
        return 0

    print(f"Inactive accounts found: {len(inactive_accounts)} (cutoff={cutoff.isoformat()})")
    for account in inactive_accounts:
        full_name = f"{account['firstname']} {account['lastname']}"
        print(
            f"- verified_user_id={account['verified_user_id']} "
            f"name={full_name} "
            f"last_sync_utc={account['last_sync_utc'] or '-'} "
            f"created_at={account['created_at']}"
        )

    if not execute:
        print("Dry run only. Re-run with --execute to apply deletion.")
        return 0

    total_deleted_users = 0
    total_deleted_tokens = 0
    total_deleted_activities = 0

    for account in inactive_accounts:
        verified_user_id = account.get("verified_user_id")
        if not isinstance(verified_user_id, int):
            continue

        revoked, revoke_error = revoke_account_if_requested(
            ctx.settings,
            account,
            revoke=revoke,
        )
        if not revoked:
            print(
                "Warning: could not revoke Strava token for "
                f"verified_user_id={verified_user_id}: {revoke_error}"
            )

        deleted = ctx.repository.delete_verified_user_data(
            verified_user_id,
            delete_activities=True,
        )
        total_deleted_users += deleted["verified_users"]
        total_deleted_tokens += deleted["oauth_tokens"]
        total_deleted_activities += deleted["activities"]

    print(
        "Inactive cleanup complete. "
        f"verified_users={total_deleted_users} "
        f"oauth_tokens={total_deleted_tokens} "
        f"activities={total_deleted_activities}"
    )
    return 0


def cleanup_activities_command(ctx: CommandContext) -> int:
    years = ctx.args.years
    execute = ctx.args.execute

    if years < 1:
        print("--years must be >= 1")
        return 1

    cutoff = datetime.now(UTC) - timedelta(days=365 * years)
    old_count = ctx.repository.count_activities_older_than(cutoff)

    print(
        "Activity retention preview. "
        f"cutoff={cutoff.isoformat()} "
        f"older_activities={old_count}"
    )

    if old_count == 0:
        return 0

    if not execute:
        print("Dry run only. Re-run with --execute to delete older activities.")
        return 0

    deleted = ctx.repository.delete_activities_older_than(cutoff)
    print(
        "Activity cleanup complete. "
        f"activities={deleted['activities']} "
        f"orphan_athletes={deleted['athletes']}"
    )
    return 0


def list_dsar_events_command(ctx: CommandContext) -> int:
    limit = ctx.args.limit
    as_json = ctx.args.json

    if limit < 1:
        print("--limit must be >= 1")
        return 1

    events = ctx.repository.list_dsar_events(limit=limit)
    if not events:
        print("No DSAR audit events found.")
        return 0

    if as_json:
        print(json.dumps(events, indent=2))
        return 0

    print(f"DSAR audit events (showing up to {limit} most recent):")
    for event in events:
        print(
            f"- event_id={event['event_id']} "
            f"verified_user_id={event['verified_user_id'] or '-'} "
            f"type={event['event_type']} "
            f"source={event['request_source']} "
            f"created_at={event['created_at']}"
        )
    return 0
