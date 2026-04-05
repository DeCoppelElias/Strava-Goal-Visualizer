"""Strava OAuth 2.0 authorization flow."""

from __future__ import annotations

import http.server
import logging
import threading
from typing import Any
from urllib.parse import parse_qs, urlencode

import requests

logger = logging.getLogger(__name__)


class StravaOAuthError(RuntimeError):
    """OAuth flow error."""

    pass


def build_authorize_url(
    client_id: int,
    redirect_uri: str = "http://localhost:8765/callback",
    scope: str = "activity:read_all,profile:read_all",
    state: str = "strava_auth",
) -> str:
    """Build Strava OAuth authorize URL.

    Args:
        client_id: Your Strava app client ID
        redirect_uri: Where Strava redirects after user approves (must match app settings)
        scope: Comma-separated scopes
        state: Anti-forgery token (simple static string for this implementation)

    Returns:
        Full Strava authorize URL to open in browser
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "approval_prompt": "force",
        "scope": scope,
        "state": state,
    }
    return f"https://www.strava.com/oauth/authorize?{urlencode(params)}"


def start_callback_listener(
    port: int = 8765,
    timeout_seconds: int = 300,
    expected_state: str | None = None,
) -> str:
    """Start local HTTP server listening for OAuth callback on localhost:{port}/callback.

    Blocks until callback received or timeout. Returns the authorization code.

    Args:
        port: Port to listen on (default 8765)
        timeout_seconds: How long to wait for callback before raising TimeoutError

    Returns:
        Authorization code from Strava

    Raises:
        TimeoutError: If no callback received within timeout
        StravaOAuthError: If callback URL is invalid or code missing
    """
    code_holder: dict[str, str | None] = {"code": None, "error": None}
    ready_event = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        """Handle single GET /callback request from Strava."""

        def do_GET(self) -> None:
            if not self.path.startswith("/callback"):
                self.send_response(404)
                self.end_headers()
                return

            try:
                # Parse query parameters
                query_start = self.path.find("?")
                if query_start == -1:
                    code_holder["error"] = "No query parameters in callback URL"
                    self.send_response(400)
                    self.end_headers()
                    ready_event.set()
                    return

                query_string = self.path[query_start + 1 :]
                params = parse_qs(query_string)

                if expected_state is not None:
                    callback_state = params.get("state", [None])[0]
                    if callback_state != expected_state:
                        code_holder["error"] = "OAuth state mismatch"
                        self.send_response(403)
                        self.end_headers()
                        ready_event.set()
                        return

                # Check for errors from Strava
                if "error" in params:
                    code_holder["error"] = params["error"][0]
                    self.send_response(403)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>Authorization denied by Strava. Close this window.</h1>")
                    ready_event.set()
                    return

                # Extract authorization code
                if "code" not in params or not params["code"]:
                    code_holder["error"] = "No 'code' parameter in callback"
                    self.send_response(400)
                    self.end_headers()
                    ready_event.set()
                    return

                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>&#10003; Authorization successful. Close this window.</h1>")
                ready_event.set()
            except Exception as e:
                logger.error("Error handling OAuth callback: %s", e)
                code_holder["error"] = str(e)
                self.send_response(500)
                self.end_headers()
                ready_event.set()

        def log_message(self, *args: Any) -> None:
            """Suppress request logging."""
            pass

    # Create server
    server = http.server.HTTPServer(("localhost", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    logger.info(
        "OAuth callback listener started on http://localhost:%s/callback (timeout=%ss)",
        port,
        timeout_seconds,
    )

    try:
        # Wait for callback or timeout
        if ready_event.wait(timeout=timeout_seconds):
            if code_holder["error"]:
                raise StravaOAuthError(f"OAuth callback error: {code_holder['error']}")
            if not code_holder["code"]:
                raise StravaOAuthError("No authorization code received")
            return code_holder["code"]
        else:
            raise TimeoutError(
                f"No OAuth callback received within {timeout_seconds}s. "
                "User may have denied authorization or closed browser."
            )
    finally:
        server.shutdown()


def exchange_code_for_tokens(
    code: str,
    client_id: int,
    client_secret: str,
    redirect_uri: str = "http://localhost:8765/callback",
    oauth_url: str = "https://www.strava.com/oauth/token",
) -> dict[str, str | int]:
    """Exchange authorization code for access token and refresh token.

    Args:
        code: Authorization code from Strava callback
        client_id: Your Strava app client ID
        client_secret: Your Strava app client secret
        redirect_uri: Must match the redirect_uri used in authorize request
        oauth_url: Strava OAuth token endpoint (can override for testing)

    Returns:
        Dict with keys: access_token, refresh_token, expires_at

    Raises:
        StravaOAuthError: If token exchange fails
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    logger.info("Exchanging OAuth code for tokens")

    try:
        response = requests.post(oauth_url, data=payload, timeout=20)
    except requests.RequestException as e:
        raise StravaOAuthError(f"Failed to reach Strava OAuth endpoint: {e}") from e

    if response.status_code >= 400:
        detail = response.text.strip()
        raise StravaOAuthError(
            f"OAuth token exchange failed with status {response.status_code}: {detail}"
        )

    try:
        result = response.json()
    except ValueError as e:
        raise StravaOAuthError(f"Invalid JSON response from Strava: {e}") from e

    if not isinstance(result, dict):
        raise StravaOAuthError("Unexpected response format from Strava OAuth")

    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token")
    expires_at = result.get("expires_at")

    if not isinstance(access_token, str) or not access_token:
        raise StravaOAuthError("Missing access_token in OAuth response")

    if not isinstance(expires_at, int) or expires_at <= 0:
        raise StravaOAuthError("Missing or invalid expires_at in OAuth response")

    logger.info("OAuth token exchange successful (expires_at=%s)", expires_at)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token or "",
        "expires_at": expires_at,
    }
