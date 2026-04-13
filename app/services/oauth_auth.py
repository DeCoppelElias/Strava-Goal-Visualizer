from __future__ import annotations

import secrets
import webbrowser
from dataclasses import dataclass
from datetime import date

from app.config import Settings
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClient, StravaClientError
from app.strava.oauth import (
    StravaOAuthError,
    build_authorize_url,
    exchange_code_for_tokens,
    start_callback_listener_with_metadata,
)

_REQUIRED_OAUTH_SCOPES = frozenset({"activity:read_all", "profile:read_all"})


def _parse_scope_value(scope_value: object) -> set[str]:
    if not isinstance(scope_value, str):
        return set()
    return {scope.strip() for scope in scope_value.split(",") if scope.strip()}


def _validate_required_permissions(
    granted_scope: str | None,
    *,
    athlete_payload: dict[str, object],
    client: StravaClient,
) -> None:
    granted_scopes = _parse_scope_value(granted_scope)
    if granted_scopes:
        missing_scopes = sorted(_REQUIRED_OAUTH_SCOPES - granted_scopes)
        if missing_scopes:
            missing = ", ".join(missing_scopes)
            raise StravaOAuthError(
                "Missing required Strava permissions: "
                f"{missing}. Please reconnect and allow all requested permissions."
            )
        return

    # Some Strava flows omit scope metadata in token/callback responses.
    # Fall back to probing required API capabilities directly.
    if not isinstance(athlete_payload.get("clubs"), list):
        raise StravaOAuthError(
            "Strava authorization is missing required profile access. "
            "Please reconnect and approve all requested permissions."
        )

    try:
        client.get_athlete_activities(
            year=date.today().year,
            per_page=1,
            page_delay_seconds=0,
            max_pages=1,
        )
    except StravaClientError as exc:
        raise StravaOAuthError(
            "Strava authorization is missing required activity access. "
            "Please reconnect and approve all requested permissions."
        ) from exc


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


def _save_user_from_athlete(
    settings: Settings,
    repository: SQLiteRepository,
    token_data: dict[str, str | int],
    *,
    granted_scope: str | None = None,
) -> AuthorizedUser:
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
    _validate_required_permissions(granted_scope, athlete_payload=athlete, client=client)

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


def begin_oauth_flow(settings: Settings, repository: SQLiteRepository) -> str:
    """Save a short-lived OAuth state and return the Strava authorize URL.

    Used by the web dashboard redirect flow. The returned URL should be
    presented to the user as a link. After approval, Strava redirects to
    APP_BASE_URL with ?code=...&state=... query parameters.
    """
    if not settings.app_base_url:
        raise ValueError(
            "APP_BASE_URL is not configured. "
            "Set it to your deployed app URL (e.g. https://your-app.onrender.com)."
        )
    state = secrets.token_urlsafe(32)
    repository.save_pending_oauth_state(state, ttl_seconds=600)
    repository.purge_expired_oauth_states()
    return build_authorize_url(
        client_id=settings.strava_client_id,
        redirect_uri=settings.app_base_url,
        state=state,
    )


def complete_oauth_flow(
    settings: Settings,
    repository: SQLiteRepository,
    code: str,
    state: str,
    granted_scope: str | None = None,
) -> AuthorizedUser:
    """Complete the web OAuth callback: validate state, exchange code, save user."""
    if not repository.consume_pending_oauth_state(state):
        raise StravaOAuthError("Invalid or expired OAuth state. Please try connecting again.")
    token_data = exchange_code_for_tokens(
        code=code,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        redirect_uri=settings.app_base_url,
    )
    return _save_user_from_athlete(
        settings,
        repository,
        token_data,
        granted_scope=granted_scope,
    )


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

    callback = start_callback_listener_with_metadata(
        port=8765,
        timeout_seconds=300,
        expected_state=oauth_state,
    )
    token_data = exchange_code_for_tokens(
        code=callback.code,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        redirect_uri=redirect_uri,
    )
    return _save_user_from_athlete(
        settings,
        repository,
        token_data,
        granted_scope=callback.granted_scope,
    )
