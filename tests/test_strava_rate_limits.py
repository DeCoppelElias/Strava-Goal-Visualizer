from __future__ import annotations

from datetime import UTC, datetime

from requests import Response

from app.strava.rate_limits import (
    get_rate_limit_wait_seconds,
    parse_rate_header_pair,
    seconds_to_next_quarter_hour,
)


def _response_with_headers(headers: dict[str, str]) -> Response:
    response = Response()
    response.status_code = 429
    response.headers.update(headers)
    return response


def test_parse_rate_header_pair_parses_two_int_values() -> None:
    assert parse_rate_header_pair("10, 200") == (10, 200)


def test_parse_rate_header_pair_returns_none_for_invalid_input() -> None:
    assert parse_rate_header_pair("bad") is None
    assert parse_rate_header_pair("1, bad") is None


def test_seconds_to_next_quarter_hour_returns_expected_seconds() -> None:
    now = datetime(2026, 4, 11, 12, 7, 30, tzinfo=UTC)
    assert seconds_to_next_quarter_hour(now) == 450


def test_get_rate_limit_wait_seconds_prefers_retry_after() -> None:
    response = _response_with_headers({"Retry-After": "17"})
    assert get_rate_limit_wait_seconds(response) == 17


def test_get_rate_limit_wait_seconds_uses_reset_header() -> None:
    now = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)
    reset_epoch = int(datetime(2026, 4, 11, 12, 0, 25, tzinfo=UTC).timestamp())
    response = _response_with_headers({"X-RateLimit-Reset": str(reset_epoch)})
    assert get_rate_limit_wait_seconds(response, now_utc=now) == 25


def test_get_rate_limit_wait_seconds_uses_usage_limit_short_window() -> None:
    now = datetime(2026, 4, 11, 12, 7, 30, tzinfo=UTC)
    response = _response_with_headers(
        {
            "X-RateLimit-Usage": "200, 500",
            "X-RateLimit-Limit": "200, 1000",
        }
    )
    assert get_rate_limit_wait_seconds(response, now_utc=now) == 450
