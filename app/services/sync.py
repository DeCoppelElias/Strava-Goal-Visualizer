from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClient
from app.strava.models import ClubActivity


@dataclass(frozen=True)
class SyncResult:
    fetched_activities: int
    stored_activities: int
    from_timestamp: datetime
    to_timestamp: datetime


@dataclass(frozen=True)
class SyncAuthorizedBatchResult:
    accounts_seen: int
    accounts_synced: int
    total_fetched_activities: int
    total_stored_activities: int


def _year_start_utc(now_utc: datetime) -> datetime:
    return datetime(now_utc.year, 1, 1, tzinfo=UTC)


def _is_run_activity(payload: dict[str, Any]) -> bool:
    return (payload.get("sport_type") or payload.get("type")) == "Run"


def _to_club_activity(
    payload: dict[str, Any],
    fallback_athlete_id: int,
    fallback_firstname: str | None,
    fallback_lastname: str | None,
) -> ClubActivity:
    athlete = payload.get("athlete")
    patched_athlete: dict[str, Any] = {}

    if isinstance(athlete, dict):
        patched_athlete = dict(athlete)

    if "id" not in patched_athlete:
        patched_athlete["id"] = fallback_athlete_id

    first = patched_athlete.get("firstname")
    if (first is None or str(first).strip() == "") and fallback_firstname:
        patched_athlete["firstname"] = fallback_firstname

    last = patched_athlete.get("lastname")
    if (last is None or str(last).strip() == "") and fallback_lastname:
        patched_athlete["lastname"] = fallback_lastname

    payload = dict(payload)
    payload["athlete"] = patched_athlete
    return ClubActivity.from_api_payload(payload)


def sync_verified_user_runs(settings: Settings, verified_user_id: int) -> SyncResult:
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    token_data = repository.get_oauth_token_by_verified_user_id(verified_user_id)
    if token_data is None:
        raise ValueError(
            f"No OAuth token found for verified user {verified_user_id}. Run oauth-authorize first."
        )

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_at = token_data.get("access_token_expires_at")
    token_id = token_data.get("token_id")

    if not isinstance(access_token, str) or not access_token:
        raise ValueError(f"OAuth token for user {verified_user_id} has no access token")
    if not isinstance(token_id, str) or not token_id:
        raise ValueError(f"OAuth token for user {verified_user_id} has no token_id")

    now_utc = datetime.now(UTC)
    year_start = _year_start_utc(now_utc)

    account = next(
        (
            row
            for row in repository.get_oauth_accounts()
            if row.get("verified_user_id") == verified_user_id
        ),
        None,
    )
    fallback_firstname = account.get("firstname") if isinstance(account, dict) else None
    fallback_lastname = account.get("lastname") if isinstance(account, dict) else None

    client = StravaClient(
        access_token=access_token,
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        access_token_expires_at=expires_at if isinstance(expires_at, int) else None,
        timeout_seconds=settings.request_timeout_seconds,
    )

    raw_activities = client.get_athlete_activities(
        year=now_utc.year,
        per_page=settings.sync_page_size,
        page_delay_seconds=settings.sync_page_delay_seconds,
        max_pages=settings.sync_max_pages,
    )

    run_activities = [
        _to_club_activity(
            activity,
            verified_user_id,
            fallback_firstname if isinstance(fallback_firstname, str) else None,
            fallback_lastname if isinstance(fallback_lastname, str) else None,
        )
        for activity in raw_activities
        if _is_run_activity(activity)
    ]
    stored = repository.upsert_activities(run_activities)
    repository.set_oauth_last_sync_utc(token_id, now_utc)

    return SyncResult(
        fetched_activities=len(raw_activities),
        stored_activities=stored,
        from_timestamp=year_start,
        to_timestamp=now_utc,
    )


def sync_all_authorized_users(settings: Settings) -> SyncAuthorizedBatchResult:
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    accounts = repository.get_oauth_accounts()
    if not accounts:
        return SyncAuthorizedBatchResult(
            accounts_seen=0,
            accounts_synced=0,
            total_fetched_activities=0,
            total_stored_activities=0,
        )

    total_fetched = 0
    total_stored = 0
    synced = 0

    for account in accounts:
        verified_user_id = account.get("verified_user_id")
        if not isinstance(verified_user_id, int):
            continue
        result = sync_verified_user_runs(settings, verified_user_id)
        total_fetched += result.fetched_activities
        total_stored += result.stored_activities
        synced += 1

    return SyncAuthorizedBatchResult(
        accounts_seen=len(accounts),
        accounts_synced=synced,
        total_fetched_activities=total_fetched,
        total_stored_activities=total_stored,
    )
