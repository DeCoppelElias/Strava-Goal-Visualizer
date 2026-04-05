from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings, load_settings
from app.logging_config import configure_logging
from app.services.oauth_auth import authorize_and_store_user
from app.services.sync import sync_all_authorized_users, sync_verified_user_runs
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClient, StravaClientError, StravaRateLimitError
from app.strava.oauth import StravaOAuthError

logger = logging.getLogger(__name__)


def _sync_command(verified_user_id: int | None = None) -> int:
    if verified_user_id is None:
        print(
            "Sync now requires OAuth-authorized users. "
            "Use --verified-user-id <id> for one user, or use 'sync-authorized' "
            "to sync all connected accounts."
        )
        return 1

    settings = load_settings()
    sync_target = f"verified_user_id={verified_user_id}"
    logger.info("Starting sync for %s", sync_target)

    try:
        result = sync_verified_user_runs(settings, verified_user_id)
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
    except StravaClientError as exc:
        print(f"Sync failed: {exc}")
        return 1
    except ValueError as exc:
        print(f"Sync failed: {exc}")
        return 1


def _sync_authorized_command() -> int:
    settings = load_settings()
    logger.info("Starting sync for all OAuth-authorized users")
    try:
        result = sync_all_authorized_users(settings)
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


def _oauth_authorize_command() -> int:
    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()
    try:
        user = authorize_and_store_user(
            settings,
            repository,
            open_browser_window=True,
        )
    except (StravaOAuthError, StravaClientError, TimeoutError, ValueError) as exc:
        print(f"OAuth authorization failed: {exc}")
        return 1

    print(
        "OAuth authorization complete. "
        f"Saved verified user {user.verified_user_id} ({user.firstname} {user.lastname}) "
        f"with token_id={user.token_id}."
    )
    return 0


def _oauth_list_command() -> int:
    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()
    accounts = repository.get_oauth_accounts()
    if not accounts:
        print("No OAuth accounts stored yet.")
        return 0

    print("Stored OAuth accounts:")
    for account in accounts:
        full_name = f"{account['firstname']} {account['lastname']}"
        print(
            f"- token_id={account['token_id']} "
            f"verified_user_id={account['verified_user_id']} "
            f"name={full_name} "
            f"email={account['email'] or '-'} "
            f"expires_at={account['access_token_expires_at']} "
            f"last_sync_utc={account['last_sync_utc'] or '-'}"
        )
    return 0


def _dashboard_command() -> int:
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", "app/dashboard/dashboard_ui.py"]
    )


def _build_strava_client_for_account(
    settings: Settings,
    account: dict[str, object],
) -> StravaClient:
    access_token = account.get("access_token")
    refresh_token = account.get("refresh_token")
    expires_at = account.get("access_token_expires_at")

    return StravaClient(
        access_token=access_token if isinstance(access_token, str) else None,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        access_token_expires_at=expires_at if isinstance(expires_at, int) else None,
        timeout_seconds=settings.request_timeout_seconds,
    )


def _revoke_account_if_requested(
    settings: Settings,
    account: dict[str, object],
    *,
    revoke: bool,
) -> tuple[bool, str | None]:
    if not revoke:
        return True, None

    try:
        client = _build_strava_client_for_account(settings, account)
        client.deauthorize()
        return True, None
    except StravaClientError as exc:
        return False, str(exc)


def _export_user_data_command(verified_user_id: int, output: str) -> int:
    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    payload = repository.export_verified_user_data(verified_user_id)
    if payload is None:
        print(f"No verified user found for id={verified_user_id}.")
        return 1

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    repository.log_dsar_event(
        verified_user_id=verified_user_id,
        event_type="export",
        request_source="cli",
        details={"result": "written", "output_path": str(output_path)},
    )

    print(
        "User data export complete. "
        f"verified_user_id={verified_user_id} "
        f"activities={len(payload.get('activities', []))} "
        f"path={output_path}"
    )
    return 0


def _forget_user_command(
    verified_user_id: int,
    *,
    revoke: bool,
    keep_activities: bool,
) -> int:
    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    account = repository.get_oauth_account_by_verified_user_id(verified_user_id)
    if account is None:
        print(f"No OAuth account found for verified_user_id={verified_user_id}.")
        return 1

    repository.log_dsar_event(
        verified_user_id=verified_user_id,
        event_type="erasure",
        request_source="cli",
        details={"result": "requested", "keep_activities": keep_activities},
    )

    revoked, revoke_error = _revoke_account_if_requested(settings, account, revoke=revoke)
    if not revoked:
        print(f"Warning: could not revoke Strava token before delete: {revoke_error}")

    deleted = repository.delete_verified_user_data(
        verified_user_id,
        delete_activities=not keep_activities,
    )
    repository.log_dsar_event(
        verified_user_id=None,
        event_type="erasure",
        request_source="cli",
        details={
            "result": "completed",
            "deleted": deleted,
            "deleted_verified_user_id": verified_user_id,
        },
    )
    print(
        "User data removal complete. "
        f"verified_users={deleted['verified_users']} "
        f"oauth_tokens={deleted['oauth_tokens']} "
        f"activities={deleted['activities']} "
        f"athletes={deleted['athletes']}"
    )
    return 0


def _cleanup_inactive_command(
    *,
    days: int,
    execute: bool,
    revoke: bool,
) -> int:
    if days < 1:
        print("--days must be >= 1")
        return 1

    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    cutoff = datetime.now(UTC) - timedelta(days=days)
    inactive_accounts = repository.list_inactive_oauth_accounts(cutoff)

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

        revoked, revoke_error = _revoke_account_if_requested(settings, account, revoke=revoke)
        if not revoked:
            print(
                "Warning: could not revoke Strava token for "
                f"verified_user_id={verified_user_id}: {revoke_error}"
            )

        deleted = repository.delete_verified_user_data(verified_user_id, delete_activities=True)
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


def _cleanup_activities_command(*, years: int, execute: bool) -> int:
    if years < 1:
        print("--years must be >= 1")
        return 1

    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    cutoff = datetime.now(UTC) - timedelta(days=365 * years)
    old_count = repository.count_activities_older_than(cutoff)

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

    deleted = repository.delete_activities_older_than(cutoff)
    print(
        "Activity cleanup complete. "
        f"activities={deleted['activities']} "
        f"orphan_athletes={deleted['athletes']}"
    )
    return 0


def _list_dsar_events_command(*, limit: int, as_json: bool) -> int:
    if limit < 1:
        print("--limit must be >= 1")
        return 1

    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    events = repository.list_dsar_events()
    if not events:
        print("No DSAR audit events found.")
        return 0

    selected = events[-limit:]
    if as_json:
        print(json.dumps(selected, indent=2))
        return 0

    print(f"DSAR audit events (showing {len(selected)} of {len(events)}):")
    for event in selected:
        print(
            f"- event_id={event['event_id']} "
            f"verified_user_id={event['verified_user_id'] or '-'} "
            f"type={event['event_type']} "
            f"source={event['request_source']} "
            f"created_at={event['created_at']}"
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strava authorized run visualizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync one OAuth-authorized user's activities",
    )
    sync_parser.add_argument(
        "--verified-user-id",
        type=int,
        default=None,
        help="Verified user id to sync (required)",
    )
    subparsers.add_parser(
        "sync-authorized",
        help="Sync all OAuth-authorized users",
    )

    subparsers.add_parser("dashboard", help="Start interactive Streamlit dashboard")
    subparsers.add_parser("oauth-authorize", help="Authorize a Strava user via OAuth")
    subparsers.add_parser("oauth-list", help="List saved OAuth accounts")

    export_parser = subparsers.add_parser(
        "export-user-data",
        help="Export one verified user's stored data to JSON",
    )
    export_parser.add_argument(
        "--verified-user-id",
        type=int,
        required=True,
        help="Verified user id to export",
    )
    export_parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output JSON path",
    )

    forget_parser = subparsers.add_parser(
        "forget-user",
        help="Delete one verified user's local data and OAuth token",
    )
    forget_parser.add_argument(
        "--verified-user-id",
        type=int,
        required=True,
        help="Verified user id to delete",
    )
    forget_parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke the user's Strava authorization before local delete",
    )
    forget_parser.add_argument(
        "--keep-activities",
        action="store_true",
        help="Keep local activities for this user while removing OAuth/account identity",
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup-inactive",
        help="Find and optionally remove inactive OAuth users",
    )
    cleanup_parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Inactive cutoff in days (default: 90)",
    )
    cleanup_parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply deletions (default is dry run)",
    )
    cleanup_parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke Strava authorizations before deletion",
    )

    cleanup_activities_parser = subparsers.add_parser(
        "cleanup-activities",
        help="Find and optionally delete activities older than a retention window",
    )
    cleanup_activities_parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Delete activities older than this many years (default: 3)",
    )
    cleanup_activities_parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply deletion (default is dry run)",
    )

    dsar_parser = subparsers.add_parser(
        "list-dsar-events",
        help="List DSAR audit log events",
    )
    dsar_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of most recent events to print (default: 50)",
    )
    dsar_parser.add_argument(
        "--json",
        action="store_true",
        help="Print events as JSON",
    )

    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()
    if args.command == "sync":
        return _sync_command(verified_user_id=getattr(args, "verified_user_id", None))
    if args.command == "dashboard":
        return _dashboard_command()
    if args.command == "sync-authorized":
        return _sync_authorized_command()
    if args.command == "oauth-authorize":
        return _oauth_authorize_command()
    if args.command == "oauth-list":
        return _oauth_list_command()
    if args.command == "export-user-data":
        return _export_user_data_command(
            verified_user_id=args.verified_user_id,
            output=args.output,
        )
    if args.command == "forget-user":
        return _forget_user_command(
            verified_user_id=args.verified_user_id,
            revoke=args.revoke,
            keep_activities=args.keep_activities,
        )
    if args.command == "cleanup-inactive":
        return _cleanup_inactive_command(
            days=args.days,
            execute=args.execute,
            revoke=args.revoke,
        )
    if args.command == "cleanup-activities":
        return _cleanup_activities_command(
            years=args.years,
            execute=args.execute,
        )
    if args.command == "list-dsar-events":
        return _list_dsar_events_command(
            limit=args.limit,
            as_json=args.json,
        )
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
