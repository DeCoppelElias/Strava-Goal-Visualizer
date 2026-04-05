from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)


class StravaClientError(RuntimeError):
    pass


class StravaRateLimitError(StravaClientError):
    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class StravaClient:
    BASE_URL = "https://www.strava.com/api/v3"
    OAUTH_URL = "https://www.strava.com/oauth/token"
    OAUTH_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"

    def __init__(
        self,
        access_token: str | None,
        *,
        client_id: int | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token_expires_at: int | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self._session = requests.Session()
        self._access_token = access_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token_expires_at = access_token_expires_at
        if access_token:
            self._session.headers.update({"Authorization": f"Bearer {access_token}"})
        self._timeout_seconds = timeout_seconds

    def get_authenticated_athlete(self) -> dict[str, Any]:
        """Fetch profile of authenticated user: {id, firstname, lastname, email, ...}."""
        response = self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/athlete",
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
                f"{self.BASE_URL}/athlete/activities",
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
                        dt = datetime.fromisoformat(
                            start_timestamp.replace("Z", "+00:00")
                        )
                        ts = dt.timestamp()
                        if ts >= year_start and ts <= year_end:
                            # Filter to Runs only
                            if (
                                activity.get("sport_type") == "Run"
                                or activity.get("type") == "Run"
                            ):
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
                logger.info(
                    "Reached year boundary at page=%s; stopping early", page
                )
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

        response = self._session.post(
            self.OAUTH_DEAUTHORIZE_URL,
            timeout=self._timeout_seconds,
        )
        if response.status_code >= 400:
            detail = response.text.strip()
            raise StravaClientError(
                "Strava deauthorize failed with status "
                f"{response.status_code}: {detail}"
            )

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        max_attempts: int = 4,
    ) -> requests.Response:
        backoff_seconds = 1.0

        for attempt in range(1, max_attempts + 1):
            self._ensure_access_token()

            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=self._timeout_seconds,
            )

            if response.status_code < 400:
                return response

            if (
                response.status_code == 401
                and self._has_refresh_credentials()
                and attempt < max_attempts
            ):
                logger.warning("Received 401, refreshing access token and retrying request")
                self._refresh_access_token()
                continue

            if response.status_code == 429:
                wait_seconds = self._get_rate_limit_wait_seconds(response)
                if wait_seconds is not None and wait_seconds <= 90 and attempt < max_attempts:
                    time.sleep(float(wait_seconds))
                    continue

                detail = response.text.strip()
                if wait_seconds is None:
                    raise StravaRateLimitError(
                        "Strava API rate limit exceeded. Retry later. "
                        f"Server response: {detail}"
                    )
                raise StravaRateLimitError(
                    "Strava API rate limit exceeded. "
                    f"Retry in about {wait_seconds} seconds. "
                    f"Server response: {detail}",
                    retry_after_seconds=wait_seconds,
                )

            if response.status_code in {500, 502, 503, 504} and attempt < max_attempts:
                logger.warning(
                    "Transient Strava API error status=%s on attempt=%s/%s, retrying in %.1fs",
                    response.status_code,
                    attempt,
                    max_attempts,
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
        return now_epoch >= (self._access_token_expires_at - 60)

    def _refresh_access_token(self) -> None:
        if not self._has_refresh_credentials():
            raise StravaClientError("Cannot refresh access token without Strava OAuth credentials")

        logger.info("Refreshing Strava access token")

        response = self._session.post(
            self.OAUTH_URL,
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
                "Strava token refresh failed with status "
                f"{response.status_code}: {detail}"
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

    def _get_rate_limit_wait_seconds(self, response: requests.Response) -> int | None:
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header and retry_after_header.isdigit():
            return max(1, int(retry_after_header))

        now_utc = datetime.now(UTC)

        for reset_header_name in ("X-ReadRateLimit-Reset", "X-RateLimit-Reset"):
            reset_value = response.headers.get(reset_header_name)
            if reset_value and reset_value.isdigit():
                reset_time = datetime.fromtimestamp(int(reset_value), tz=UTC)
                return max(1, int((reset_time - now_utc).total_seconds()))

        usage_header = response.headers.get("X-RateLimit-Usage")
        limit_header = response.headers.get("X-RateLimit-Limit")
        if usage_header and limit_header:
            usage = self._parse_rate_header_pair(usage_header)
            limit = self._parse_rate_header_pair(limit_header)
            if usage is not None and limit is not None:
                short_usage, long_usage = usage
                short_limit, long_limit = limit

                if short_usage >= short_limit:
                    return self._seconds_to_next_quarter_hour(now_utc)

                if long_usage >= long_limit:
                    today_start = datetime(
                        now_utc.year,
                        now_utc.month,
                        now_utc.day,
                        tzinfo=UTC,
                    )
                    tomorrow = today_start + timedelta(days=1)
                    return max(1, int((tomorrow - now_utc).total_seconds()))

        return None

    def _parse_rate_header_pair(self, value: str) -> tuple[int, int] | None:
        parts = value.split(",")
        if len(parts) != 2:
            return None
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None

    def _seconds_to_next_quarter_hour(self, now_utc: datetime) -> int:
        minute_bucket = (now_utc.minute // 15) + 1
        next_minute = minute_bucket * 15
        base_hour = datetime(
            now_utc.year,
            now_utc.month,
            now_utc.day,
            now_utc.hour,
            tzinfo=UTC,
        )
        next_window = base_hour + timedelta(minutes=next_minute)
        return max(1, int((next_window - now_utc).total_seconds()))
