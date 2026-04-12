# API Usage Documentation — Goal Visualizer

## Strava API Version

Strava v3 REST API — https://developers.strava.com/docs/reference/

---

## Scopes Requested

| Scope | Endpoints Used | Purpose |
|---|---|---|
| `activity:read_all` | `GET /athlete/activities` | Fetch authenticated user's Run activities |
| `profile:read_all` | `GET /athlete` | Fetch athlete profile (id, firstname, lastname) |

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
**No user data is read from this endpoint**

---

### 4. `POST /oauth/deauthorize`

**When:** When the user clicks "Disconnect & Delete Everything" in Privacy Settings
**Purpose:** Revoke the app's Strava authorization for that user
**No user data is read from this endpoint**

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

The app reads and respects Strava's rate limit response headers on every request:

| Condition | Behaviour |
|---|---|
| `X-RateLimit-Usage` short-term bucket exceeded | Wait until the next 15-minute window |
| `X-RateLimit-Usage` daily bucket exceeded | Wait until UTC midnight |
| `Retry-After` header present | Wait the specified number of seconds |
| HTTP 429 with wait > 300 s | Raise error; do not retry automatically |
| HTTP 5xx transient error | Exponential backoff (1 s → 2 s → 4 s), up to 3 retries |
| HTTP 401 token expired | Auto-refresh access token, then retry once |

### Summary

The app is designed to be a light, considerate API consumer:
- Maximum ~60 API calls per full sync (60 pages × 1 request each)
- At most 1 full sync per user per 24 hours under normal operation
- Proactive rate-limit detection avoids unnecessary 429 responses
- Activity filtering stops pagination early, reducing total calls significantly in practice
