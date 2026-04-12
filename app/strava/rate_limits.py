from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests

from app.strava.constants import RATE_LIMIT_RESET_HEADERS


def parse_rate_header_pair(value: str) -> tuple[int, int] | None:
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def seconds_to_next_quarter_hour(now_utc: datetime) -> int:
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


def get_rate_limit_wait_seconds(
    response: requests.Response,
    *,
    now_utc: datetime | None = None,
) -> int | None:
    retry_after_header = response.headers.get("Retry-After")
    if retry_after_header and retry_after_header.isdigit():
        return max(1, int(retry_after_header))

    if now_utc is None:
        now_utc = datetime.now(UTC)

    for reset_header_name in RATE_LIMIT_RESET_HEADERS:
        reset_value = response.headers.get(reset_header_name)
        if reset_value and reset_value.isdigit():
            reset_time = datetime.fromtimestamp(int(reset_value), tz=UTC)
            return max(1, int((reset_time - now_utc).total_seconds()))

    usage_header = response.headers.get("X-RateLimit-Usage")
    limit_header = response.headers.get("X-RateLimit-Limit")
    if usage_header and limit_header:
        usage = parse_rate_header_pair(usage_header)
        limit = parse_rate_header_pair(limit_header)
        if usage is not None and limit is not None:
            short_usage, long_usage = usage
            short_limit, long_limit = limit

            if short_usage >= short_limit:
                return seconds_to_next_quarter_hour(now_utc)

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
