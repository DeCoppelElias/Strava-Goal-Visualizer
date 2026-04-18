# API Usage Documentation — Goal Visualizer

## Strava API Version

Strava v3 REST API — https://developers.strava.com/docs/reference/

---

## Scopes Requested

| Scope | Endpoints Used | Purpose |
|---|---|---|
| `activity:read_all` | `GET /athlete/activities` | Fetch all Run activities including those set to "Only You" visibility. `activity:read` would exclude private activities, causing under-counted progress for athletes with private runs. |
| `profile:read_all` | `GET /athlete` | Required for the `clubs` field in the athlete response. Club memberships are read at OAuth time and stored locally to power the club leaderboard access check and club-scoped sync. Under `read` scope, `clubs` is absent from the response and the club leaderboard feature does not work. |

---

## Endpoints Called

### 1. `GET /athlete`

**When:** Once per OAuth authorization, and once per identity verification in Privacy Settings
**Purpose:** Retrieve the athlete's id and display name to associate their account
**Fields used:** `id`, `firstname`, `lastname`
**Fields ignored:** All others (email, profile photo, location, etc.)

---

### 2. `GET /athlete/activities`

**When:** During each sync cycle for an authorized user
**Purpose:** Fetch Run activities for the current calendar year
**Filters applied before storage:**
- `sport_type == "Run"` (or legacy `type == "Run"`) — non-run activities are discarded
- `start_date` within the current year — older activities are not stored

**Fields used from each activity:**
`id`, `name`, `distance`, `moving_time`, `elapsed_time`, `total_elevation_gain`,
`sport_type`, `start_date`, `athlete.id`, `athlete.firstname`, `athlete.lastname`

**Fields ignored:** segment efforts, splits, kudos, comments, photos, maps, heart rate,
power data, and all other fields not listed above

---

### 3. `POST /oauth/token`

**When:** Initial token exchange after OAuth authorization; automatic token refresh when
access token expires
**Purpose:** Obtain and maintain valid access tokens
**No athlete activity/profile data is read from this endpoint**

Notes:
- Token exchange response fields used: `access_token`, `refresh_token`, `expires_at`
- Accepted scopes are read from the OAuth callback (`scope` query parameter) when present
- Latest refresh/access token values are persisted after refresh during sync

---

### 4. `POST /oauth/deauthorize`

**When:** When the user clicks "Disconnect & Delete Everything" in Privacy Settings
**Purpose:** Revoke the app's Strava authorization for that user
**No user data is read from this endpoint**

Request details:
- Sends `access_token` in the deauthorize request payload
- Uses the authenticated token context from the current account session

---

## OAuth Callback Validation

After user approval, Strava redirects with callback query parameters including `code`, `state`,
and typically `scope`.

Validation behavior:
- `state` is required and must match a saved short-lived pending state (CSRF protection)
- If callback `scope` is present, required permissions are validated immediately
- If callback `scope` is absent, capability probes are used (`GET /athlete` clubs field and
  a minimal `GET /athlete/activities` request)

The app requests `approval_prompt=auto` by default to avoid unnecessary repeated consent prompts.

---

## Sync Behaviour and Rate Limit Strategy

### Sync Frequency

| Trigger | Frequency |
|---|---|
| Auto-sync (dashboard load) | At most once per 24 hours per user |
| Manual sync (user-initiated) | At most once per hour per user (cooldown enforced) |
| CLI batch sync | Operator-triggered; same per-user cooldown applies |

### Pagination

- Page size: 100 activities per request
- Page delay: 1.1 seconds between pages (exceeds Strava's 1-second minimum)
- Maximum pages per sync: 60 (hard cap to prevent runaway fetches)
- Early exit: pagination stops as soon as an activity older than Jan 1 of the current year
  is found — no unnecessary pages are fetched

### HTTP Rate Limit Handling

On every 429 response, the app calculates the required wait time from response headers, then decides whether to auto-wait or raise an error immediately:

| Condition | Behaviour |
|---|---|
| HTTP 429, calculated wait ≤ 5 s | Sleep for the indicated duration, then retry |
| HTTP 429, calculated wait > 5 s | Raise error immediately — no long blocking waits |
| HTTP 429, no wait duration in headers | Raise error immediately |
| HTTP 5xx transient error | Exponential backoff (1 s → 2 s → 4 s), up to 3 retries |
| HTTP 401 token expired | Auto-refresh access token, then retry once |

**How wait duration is calculated (in priority order):**
1. `Retry-After` header — used directly as seconds
2. `X-ReadRateLimit-Reset` / `X-RateLimit-Reset` header — seconds until the reset timestamp
3. `X-RateLimit-Usage` + `X-RateLimit-Limit` headers — short-term bucket exceeded → seconds to next quarter-hour boundary; daily bucket exceeded → seconds to next UTC midnight

If the computed wait exceeds 5 seconds (e.g., a 15-minute or daily rate limit), the app raises a `StravaRateLimitError` immediately rather than blocking. This keeps the dashboard responsive for users.

### Summary

The app is designed to be a light, considerate API consumer:
- Maximum ~60 API calls per full sync (60 pages × 1 request each)
- At most 1 full sync per user per 24 hours under normal operation
- Proactive rate-limit detection avoids unnecessary 429 responses
- Activity filtering stops pagination early, reducing total calls significantly in practice
