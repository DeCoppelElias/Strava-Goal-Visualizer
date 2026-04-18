from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from requests import Response

from app.strava import client as client_module
from app.strava.client import StravaClient, StravaClientError, StravaRateLimitError


def _response(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    body_text: str = "",
) -> Response:
    response = Response()
    response.status_code = status_code
    if headers:
        response.headers.update(headers)
    response._content = body_text.encode("utf-8")
    return response


def _json_response(status_code: int, payload: dict[str, object]) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def test_request_with_retry_retries_transient_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StravaClient(access_token="token")
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.request.side_effect = [
        _response(503, body_text="temporary failure"),
        _response(200, body_text="ok"),
    ]
    client._session = fake_session

    sleep_calls: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = client._request_with_retry("GET", "https://example.test/athlete")

    assert result.status_code == 200
    assert fake_session.request.call_count == 2
    assert sleep_calls == [1.0]


def test_request_with_retry_refreshes_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StravaClient(
        access_token="token",
        client_id=123,
        client_secret="secret",
        refresh_token="refresh",
    )
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.request.side_effect = [
        _response(401, body_text="expired"),
        _response(200, body_text="ok"),
    ]
    client._session = fake_session

    refresh_mock = MagicMock()
    monkeypatch.setattr(client, "_refresh_access_token", refresh_mock)

    result = client._request_with_retry("GET", "https://example.test/athlete")

    assert result.status_code == 200
    refresh_mock.assert_called_once()


def test_request_with_retry_auto_waits_for_short_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StravaClient(access_token="token", rate_limit_auto_wait_max_seconds=5)
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.request.side_effect = [
        _response(429, body_text="rate limited"),
        _response(200, body_text="ok"),
    ]
    client._session = fake_session

    sleep_calls: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(client_module, "get_rate_limit_wait_seconds", lambda response: 3)

    result = client._request_with_retry("GET", "https://example.test/athlete")

    assert result.status_code == 200
    assert sleep_calls == [3.0]


def test_request_with_retry_raises_rate_limit_for_long_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StravaClient(access_token="token", rate_limit_auto_wait_max_seconds=5)
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.request.return_value = _response(429, body_text="rate limited")
    client._session = fake_session

    monkeypatch.setattr(client_module, "get_rate_limit_wait_seconds", lambda response: 30)

    with pytest.raises(StravaRateLimitError) as exc_info:
        client._request_with_retry("GET", "https://example.test/athlete")

    assert exc_info.value.retry_after_seconds == 30


def test_token_expiry_skew_is_configurable() -> None:
    now_epoch = int(datetime.now(UTC).timestamp())

    client_with_default_skew = StravaClient(
        access_token="token",
        access_token_expires_at=now_epoch + 30,
    )
    assert client_with_default_skew._token_expires_soon() is True

    client_with_small_skew = StravaClient(
        access_token="token",
        access_token_expires_at=now_epoch + 30,
        token_expiry_skew_seconds=10,
    )
    assert client_with_small_skew._token_expires_soon() is False


def test_refresh_access_token_uses_configured_oauth_url() -> None:
    custom_oauth_url = "https://api.example.test/oauth/token"
    client = StravaClient(
        access_token="token",
        client_id=123,
        client_secret="secret",
        refresh_token="refresh",
        oauth_url=custom_oauth_url,
    )
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.post.return_value = _json_response(
        200,
        {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_at": 1893456000,
        },
    )
    client._session = fake_session

    client._refresh_access_token()

    call = fake_session.post.call_args
    assert call is not None
    assert call.args[0] == custom_oauth_url


def test_refresh_access_token_raises_on_http_error() -> None:
    client = StravaClient(
        access_token="token",
        client_id=123,
        client_secret="secret",
        refresh_token="refresh",
    )
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.post.return_value = _response(400, body_text="invalid refresh token")
    client._session = fake_session

    with pytest.raises(StravaClientError, match="token refresh failed"):
        client._refresh_access_token()


def test_deauthorize_sends_access_token_payload() -> None:
    client = StravaClient(access_token="token")
    fake_session = MagicMock()
    fake_session.headers = {"Authorization": "Bearer token"}
    fake_session.post.return_value = _response(200, body_text="ok")
    client._session = fake_session

    client.deauthorize()

    call = fake_session.post.call_args
    assert call is not None
    assert call.kwargs["data"] == {"access_token": "token"}


def test_current_token_state_reflects_refresh_updates() -> None:
    client = StravaClient(
        access_token="token",
        client_id=123,
        client_secret="secret",
        refresh_token="refresh",
    )
    fake_session = MagicMock()
    fake_session.headers = {}
    fake_session.post.return_value = _json_response(
        200,
        {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_at": 1893456000,
        },
    )
    client._session = fake_session

    client._refresh_access_token()
    token_state = client.current_token_state()

    assert token_state["access_token"] == "new_token"
    assert token_state["refresh_token"] == "new_refresh"
    assert token_state["access_token_expires_at"] == 1893456000
