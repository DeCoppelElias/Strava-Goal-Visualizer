# Use Case — Goal Visualizer

## App Summary

**App name:** Goal Visualizer
**Website:** https://strava-goal-visualizer.onrender.com
**About page:** https://DeCoppelElias.github.io/Strava-Goal-Visualizer/about.html
**Privacy policy:** https://DeCoppelElias.github.io/Strava-Goal-Visualizer/privacy.html
**Support email:** goalvisualizer.support@gmail.com

---

## What the App Does

Goal Visualizer is a personal analytics dashboard that helps small running communities
track collective progress toward annual running goals using their Strava activity data.

Users authorize their Strava account via OAuth. The app fetches their Run activities and
displays:

- **Personal progress view:** Year-to-date distance toward a configurable annual goal
  (default 365 km), with a cumulative progress chart and an on-track guide line
- **Club leaderboard view:** Ranked progress table for all connected members of a given
  Strava club, showing distance, run count, completion percentage, and remaining km
- **Goal preferences:** Each user can set their own annual mileage target
- **Privacy controls:** Users can export all their locally stored data or permanently
  delete their account and all associated records in a single in-app action

---

## Why These Scopes Are Needed

| Scope | Reason |
|---|---|
| `activity:read_all` | Fetch the authenticated user's Run activities to compute distance and progress metrics. `activity:read` would exclude activities set to "Only You" visibility, causing under-counting for private athletes. |
| `profile:read_all` | The `GET /athlete` endpoint only returns the `clubs` field under `profile:read_all`. This field is read at OAuth time to store each user's club memberships, which powers the club leaderboard access check and club sync. Without it, the club leaderboard feature would not work. |

No other scopes are requested or used.

---

## Current and Requested Scale

| | Athletes |
|---|---|
| Current (sandbox mode) | 1 |
| Requesting approval for | 100 |

The app is currently in Strava API sandbox mode with a single connected user. Once
approval is granted, it will be shared with friends and small running clubs. It is not
marketed for broad public use and has no advertising or monetization.

---

## Data Flow

1. User clicks "Connect Strava Account" in the dashboard sidebar
2. App redirects user to Strava OAuth authorization page
3. User approves access; Strava redirects back with an authorization code
4. App exchanges the code for an access + refresh token pair
5. Callback `state` is validated and callback `scope` is checked when present
6. Tokens are stored locally in SQLite, **encrypted at rest using Fernet**
7. Accepted callback scopes are stored for troubleshooting
8. App fetches the user's Run activities for the current year via the Strava v3 API
9. Activity records are stored locally in SQLite for dashboard analytics
10. Dashboard renders progress metrics and charts from local storage
11. Tokens are auto-refreshed when expired and the latest refresh/access token values are persisted

---

## Data Handling Summary

- **Stored:** Athlete id, first/last name, optional email if provided by Strava,
  accepted OAuth scope metadata, OAuth tokens (encrypted), Run activity records,
  privacy request audit log
- **Not stored:** Phone, precise address, payment data, social graph data, photos,
  heart rate, or other activity fields beyond the documented analytics set
- **Not shared:** No data is sold, shared with third parties, or used for advertising
- **Deletion:** Users can delete all their stored data instantly from the Privacy Settings
  screen; the app also attempts to revoke Strava authorization at that time
- **Retention:** Inactive accounts are cleaned up after 90 days; activity records older
  than 3 years are pruned on a scheduled basis

---

## Infrastructure

- **Hosting:** Render (HTTPS enforced via proxy layer)
- **Database:** SQLite (local to the app instance)
- **Language/framework:** Python 3.11+, Streamlit
- **Source code:** https://github.com/DeCoppelElias/Strava-Goal-Visualizer (MIT License)
