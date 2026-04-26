from __future__ import annotations

from collections.abc import Callable

from app.cli.commands.maintenance import (
    cleanup_activities_command,
    cleanup_inactive_command,
    list_dsar_events_command,
)
from app.cli.commands.oauth import oauth_authorize_command, oauth_list_command
from app.cli.commands.privacy import export_user_data_command, forget_user_command
from app.cli.commands.sync import sync_authorized_command, sync_command
from app.cli.context import CommandContext
from app.cli.parser import parse_args
from app.logging_config import configure_logging

CommandHandler = Callable[[CommandContext], int]

COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "sync": sync_command,
    "sync-authorized": sync_authorized_command,
    "oauth-authorize": oauth_authorize_command,
    "oauth-list": oauth_list_command,
    "export-user-data": export_user_data_command,
    "forget-user": forget_user_command,
    "cleanup-inactive": cleanup_inactive_command,
    "cleanup-activities": cleanup_activities_command,
    "list-dsar-events": list_dsar_events_command,
}


def main() -> int:
    configure_logging()
    args = parse_args()
    ctx = CommandContext(args=args)
    handler = COMMAND_HANDLERS.get(args.command)
    if handler is not None:
        return handler(ctx)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
