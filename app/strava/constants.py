from __future__ import annotations

DEFAULT_BASE_URL = "https://www.strava.com/api/v3"
DEFAULT_OAUTH_URL = "https://www.strava.com/oauth/token"
DEFAULT_OAUTH_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRY_ATTEMPTS = 4
DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
DEFAULT_TOKEN_EXPIRY_SKEW_SECONDS = 60
DEFAULT_RATE_LIMIT_AUTO_WAIT_MAX_SECONDS = 5

TRANSIENT_HTTP_STATUS_CODES = frozenset({500, 502, 503, 504})
RATE_LIMIT_RESET_HEADERS = ("X-ReadRateLimit-Reset", "X-RateLimit-Reset")
