from __future__ import annotations

import argparse


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
