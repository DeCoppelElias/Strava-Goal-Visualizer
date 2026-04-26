from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import requests

from app.strava.constants import (
    DEFAULT_BASE_URL,
    DEFAULT_INITIAL_BACKOFF_SECONDS,
    DEFAULT_MAX_RETRY_ATTEMPTS,
    DEFAULT_OAUTH_DEAUTHORIZE_URL,
    DEFAULT_OAUTH_URL,
    DEFAULT_RATE_LIMIT_AUTO_WAIT_MAX_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_EXPIRY_SKEW_SECONDS,
    TRANSIENT_HTTP_STATUS_CODES,
)
from app.strava.rate_limits import get_rate_limit_wait_seconds

logger = logging.getLogger(__name__)


class StravaClientError(RuntimeError):
    pass


class StravaRateLimitError(StravaClientError):
    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class StravaClient:
    BASE_URL = DEFAULT_BASE_URL
    OAUTH_URL = DEFAULT_OAUTH_URL
    OAUTH_DEAUTHORIZE_URL = DEFAULT_OAUTH_DEAUTHORIZE_URL

    def __init__(
        self,
        access_token: str | None,
        *,
        client_id: int | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token_expires_at: int | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        oauth_url: str = DEFAULT_OAUTH_URL,
        oauth_deauthorize_url: str = DEFAULT_OAUTH_DEAUTHORIZE_URL,
        max_retry_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS,
        initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        token_expiry_skew_seconds: int = DEFAULT_TOKEN_EXPIRY_SKEW_SECONDS,
        rate_limit_auto_wait_max_seconds: int = DEFAULT_RATE_LIMIT_AUTO_WAIT_MAX_SECONDS,
    ) -> None:
        self._session = requests.Session()
        self._access_token = access_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token_expires_at = access_token_expires_at
        self._base_url = base_url
        self._oauth_url = oauth_url
        self._oauth_deauthorize_url = oauth_deauthorize_url
        self._max_retry_attempts = max(1, max_retry_attempts)
        self._initial_backoff_seconds = max(0.0, initial_backoff_seconds)
        self._token_expiry_skew_seconds = max(0, token_expiry_skew_seconds)
        self._rate_limit_auto_wait_max_seconds = max(0, rate_limit_auto_wait_max_seconds)
        if access_token:
            self._session.headers.update({"Authorization": f"Bearer {access_token}"})
        self._timeout_seconds = timeout_seconds

    def get_authenticated_athlete(self) -> dict[str, Any]:
        """Fetch profile of authenticated user: {id, firstname, lastname, email, ...}."""
        response = self._request_with_retry(
            "GET",
            f"{self._base_url}/athlete",
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise StravaClientError("Unexpected response format from Strava athlete endpoint")
        return payload

    def get_athlete_activities(
        self,
        year: int,
        *,
        per_page: int = 200,
        page_delay_seconds: float = 1.1,
        max_pages: int = 60,
    ) -> list[dict[str, Any]]:
        """
        Fetch activities for authenticated user in a specific year, filtered to Runs only.
        Paginate through all results for the year.
        """
        all_activities: list[dict[str, Any]] = []
        page = 1

        # Date range: Jan 1 to Dec 31 of given year
        year_start = datetime(year, 1, 1, tzinfo=UTC).timestamp()
        year_end = datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()

        logger.info("Starting fetch of athlete activities for year=%s", year)

        while True:
            if page > max_pages:
                logger.warning(
                    "Reached page limit (%s) while fetching athlete activities", max_pages
                )
                break

            params = {"page": page, "per_page": per_page}
            logger.info("Fetching athlete activities page=%s per_page=%s", page, per_page)

            response = self._request_with_retry(
                "GET",
                f"{self._base_url}/athlete/activities",
                params=params,
            )
            page_payload = response.json()
            if not isinstance(page_payload, list):
                raise StravaClientError("Unexpected response format from Strava API")

            if not page_payload:
                logger.info("Reached end of pagination at page=%s", page)
                break

            # Filter to activities within the year
            filtered_activities = []
            reached_year_boundary = False
            for activity in page_payload:
                start_timestamp = activity.get("start_date")
                if start_timestamp:
                    try:
                        dt = datetime.fromisoformat(start_timestamp.replace("Z", "+00:00"))
                        ts = dt.timestamp()
                        if ts >= year_start and ts <= year_end:
                            # Filter to Runs only
                            if activity.get("sport_type") == "Run" or activity.get("type") == "Run":
                                filtered_activities.append(activity)
                        elif ts < year_start:
                            reached_year_boundary = True
                    except ValueError:
                        pass

            all_activities.extend(filtered_activities)
            logger.info(
                "Page %s returned %s activities (%s runs in year, running total=%s)",
                page,
                len(page_payload),
                len(filtered_activities),
                len(all_activities),
            )

            if reached_year_boundary:
                logger.info("Reached year boundary at page=%s; stopping early", page)
                break

            page += 1
            if page_delay_seconds > 0:
                time.sleep(page_delay_seconds)

        logger.info(
            "Athlete activities fetch complete: got %s total runs for year %s",
            len(all_activities),
            year,
        )
        return all_activities

    def deauthorize(self) -> None:
        self._ensure_access_token()

        access_token = self._access_token
        if not isinstance(access_token, str) or not access_token:
            raise StravaClientError("Cannot deauthorize without a valid access token")

        response = self._session.post(
            self._oauth_deauthorize_url,
            data={"access_token": access_token},
            timeout=self._timeout_seconds,
        )
        if response.status_code >= 400:
            detail = response.text.strip()
            raise StravaClientError(
                "Strava deauthorize failed with status " f"{response.status_code}: {detail}"
            )

    def current_token_state(self) -> dict[str, str | int | None]:
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "access_token_expires_at": self._access_token_expires_at,
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        max_attempts: int | None = None,
    ) -> requests.Response:
        effective_max_attempts = max_attempts or self._max_retry_attempts
        backoff_seconds = self._initial_backoff_seconds

        for attempt in range(0, effective_max_attempts):
            self._ensure_access_token()

            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._timeout_seconds,
            )

            if response.status_code < 400:
                return response

            if response.status_code == 401 and self._has_refresh_credentials():
                logger.warning("Received 401, refreshing access token and retrying request")
                self._refresh_access_token()
                continue

            if response.status_code == 429:
                wait_seconds = get_rate_limit_wait_seconds(response)
                if (
                    wait_seconds is not None
                    and wait_seconds <= self._rate_limit_auto_wait_max_seconds
                ):
                    time.sleep(float(wait_seconds))
                    continue

                detail = response.text.strip()
                if wait_seconds is None:
                    raise StravaRateLimitError(
                        "Strava API rate limit exceeded. Retry later. " f"Server response: {detail}"
                    )
                raise StravaRateLimitError(
                    "Strava API rate limit exceeded. "
                    f"Retry in about {wait_seconds} seconds. "
                    f"Server response: {detail}",
                    retry_after_seconds=wait_seconds,
                )

            if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
                logger.warning(
                    "Transient Strava API error status=%s on attempt=%s/%s, retrying in %.1fs",
                    response.status_code,
                    attempt,
                    effective_max_attempts,
                    backoff_seconds,
                )
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            detail = response.text.strip()
            raise StravaClientError(
                f"Strava API request failed with status {response.status_code}: {detail}"
            )

        raise StravaClientError("Strava API request failed after retries")

    def _ensure_access_token(self) -> None:
        if self._access_token and not self._token_expires_soon():
            return

        if not self._has_refresh_credentials():
            raise StravaClientError(
                "No valid Strava access token available. Connect an account via OAuth and "
                "ensure STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET are configured."
            )

        self._refresh_access_token()

    def _has_refresh_credentials(self) -> bool:
        return bool(self._client_id and self._client_secret and self._refresh_token)

    def _token_expires_soon(self) -> bool:
        if self._access_token_expires_at is None:
            return False
        now_epoch = int(datetime.now(UTC).timestamp())
        return now_epoch >= (self._access_token_expires_at - self._token_expiry_skew_seconds)

    def _refresh_access_token(self) -> None:
        if not self._has_refresh_credentials():
            raise StravaClientError("Cannot refresh access token without Strava OAuth credentials")

        logger.info("Refreshing Strava access token")

        response = self._session.post(
            self._oauth_url,
            data={
                "client_id": str(self._client_id),
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            timeout=self._timeout_seconds,
        )

        if response.status_code >= 400:
            detail = response.text.strip()
            raise StravaClientError(
                "Strava token refresh failed with status " f"{response.status_code}: {detail}"
            )

        payload = response.json()
        if not isinstance(payload, dict):
            raise StravaClientError("Unexpected response format from Strava OAuth token endpoint")

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise StravaClientError("Strava OAuth refresh response is missing access_token")

        self._access_token = access_token
        self._session.headers.update({"Authorization": f"Bearer {access_token}"})

        refresh_token = payload.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            self._refresh_token = refresh_token

        expires_at = payload.get("expires_at")
        if isinstance(expires_at, int):
            self._access_token_expires_at = expires_at
            logger.info("Access token refreshed (expires_at=%s)", expires_at)
