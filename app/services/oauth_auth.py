from __future__ import annotations

import secrets
import webbrowser
from dataclasses import dataclass

from app.config import Settings
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClient
from app.strava.oauth import (
    StravaOAuthError,
    build_authorize_url,
    exchange_code_for_tokens,
    start_callback_listener,
)


@dataclass(frozen=True)
class AuthorizedUser:
    verified_user_id: int
    firstname: str
    lastname: str
    email: str | None
    token_id: str


def _extract_club_ids(athlete_payload: dict[str, object]) -> list[int]:
    clubs = athlete_payload.get("clubs")
    if not isinstance(clubs, list):
        return []

    club_ids: list[int] = []
    for club in clubs:
        if not isinstance(club, dict):
            continue
        club_id = club.get("id")
        if isinstance(club_id, int):
            club_ids.append(club_id)
    return club_ids


def authorize_and_store_user(
    settings: Settings,
    repository: SQLiteRepository,
    *,
    open_browser_window: bool = True,
) -> AuthorizedUser:
    redirect_uri = "http://localhost:8765/callback"
    oauth_state = secrets.token_urlsafe(32)
    authorize_url = build_authorize_url(
        client_id=settings.strava_client_id,
        redirect_uri=redirect_uri,
        state=oauth_state,
    )

    if open_browser_window:
        webbrowser.open(authorize_url)

    code = start_callback_listener(
        port=8765,
        timeout_seconds=300,
        expected_state=oauth_state,
    )
    token_data = exchange_code_for_tokens(
        code=code,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        redirect_uri=redirect_uri,
    )

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_at = token_data.get("expires_at")

    if not isinstance(access_token, str) or not access_token:
        raise StravaOAuthError("OAuth token response missing access token")
    if not isinstance(expires_at, int):
        raise StravaOAuthError("OAuth token response missing expires_at")

    client = StravaClient(
        access_token=access_token,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        access_token_expires_at=expires_at,
        timeout_seconds=settings.request_timeout_seconds,
    )

    athlete = client.get_authenticated_athlete()
    verified_user_id = athlete.get("id")
    firstname = athlete.get("firstname")
    lastname = athlete.get("lastname")
    email = athlete.get("email")

    if not isinstance(verified_user_id, int):
        raise StravaOAuthError("Authenticated athlete response missing id")
    if not isinstance(firstname, str) or not firstname:
        raise StravaOAuthError("Authenticated athlete response missing firstname")
    if not isinstance(lastname, str) or not lastname:
        raise StravaOAuthError("Authenticated athlete response missing lastname")

    repository.save_verified_user(
        verified_user_id=verified_user_id,
        firstname=firstname,
        lastname=lastname,
        email=email if isinstance(email, str) else None,
    )
    repository.replace_verified_user_clubs(
        verified_user_id=verified_user_id,
        club_ids=_extract_club_ids(athlete),
    )

    token_id = f"verified_{verified_user_id}"
    repository.save_oauth_token(
        token_id=token_id,
        verified_user_id=verified_user_id,
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        access_token_expires_at=expires_at,
    )

    return AuthorizedUser(
        verified_user_id=verified_user_id,
        firstname=firstname,
        lastname=lastname,
        email=email if isinstance(email, str) else None,
        token_id=token_id,
    )
