# Screenshots Guide — Goal Visualizer

Screenshots to capture for the Strava app submission.
Save files into this folder: `docs/strava-submission/screenshots/`

---

## Required Screenshots

### 1. `01_dashboard_personal.png` — Personal progress view
**URL:** http://localhost:8501 (default view, logged in as yourself)

**What to show:**
- Sidebar with your connected account listed
- Main area with the progress chart (Jan–Dec cumulative line)
- The on-track guide line visible
- Year selector visible

**Steps:**
1. `python main.py sync --verified-user-id <your-id>` to ensure data is present
2. Open http://localhost:8501
3. Take full-page screenshot

---

### 2. `02_dashboard_club.png` — Club leaderboard view
**URL:** http://localhost:8501/?club_id=<your-club-id>

**What to show:**
- Club leaderboard table with multiple athletes
- Distance, run count, completion % columns visible
- "Sync club" button visible in sidebar

**Steps:**
1. Open http://localhost:8501/?club_id=<your-strava-club-id>
2. Take full-page screenshot

---

### 3. `03_privacy_settings.png` — Privacy Settings screen
**URL:** http://localhost:8501 → sidebar → Privacy Settings

**What to show:**
- The short privacy notice text
- The four link buttons: About / Privacy policy / Terms / Data deletion
- "Verify My Identity With Strava" button
- "Download My Data (JSON)" button (greyed out — before verification)
- "Disconnect & Delete Everything" button (greyed out — before verification)

**Steps:**
1. Open the dashboard and go to Privacy Settings in the sidebar
2. Do NOT verify identity yet (so buttons are shown in disabled state)
3. Take full-page screenshot

---

### 4. `04_oauth_connect.png` — OAuth connect flow
**What to show:**
- The "Connect Strava Account" button in the sidebar
- Ideally the Strava authorization page open in browser (shows scopes requested)

**Steps:**
1. Open the dashboard with no connected accounts
2. Click "Connect Strava Account" to trigger the OAuth flow
3. Screenshot the browser showing the Strava authorization page
   (shows "Goal Visualizer wants to access your account" with scopes listed)

---

## Tips

- Use a real account with at least a few runs so charts are populated
- Blur or crop out anything sensitive (full name, precise location data)
- 1280×800 px or larger recommended
- PNG format preferred; JPEG is acceptable

---

## After Capturing

Rename files exactly as listed above and place them in:
`docs/strava-submission/screenshots/`

Then commit:
```
git add docs/strava-submission/screenshots/
git commit -m "Add Strava submission screenshots"
```
