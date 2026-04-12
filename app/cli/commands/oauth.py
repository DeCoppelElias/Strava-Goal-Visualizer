from __future__ import annotations

from app.cli.context import CommandContext
from app.services.oauth_auth import authorize_and_store_user
from app.strava.client import StravaClientError
from app.strava.oauth import StravaOAuthError


def oauth_authorize_command(ctx: CommandContext) -> int:
    try:
        user = authorize_and_store_user(
            ctx.settings,
            ctx.repository,
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


def oauth_list_command(ctx: CommandContext) -> int:
    accounts = ctx.repository.get_oauth_accounts()
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
