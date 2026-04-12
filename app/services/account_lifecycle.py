from __future__ import annotations

from app.config import Settings
from app.strava.client import StravaClient, StravaClientError


def build_strava_client_for_account(
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


def revoke_account_if_requested(
    settings: Settings,
    account: dict[str, object],
    *,
    revoke: bool,
) -> tuple[bool, str | None]:
    if not revoke:
        return True, None

    try:
        client = build_strava_client_for_account(settings, account)
        client.deauthorize()
        return True, None
    except StravaClientError as exc:
        return False, str(exc)
