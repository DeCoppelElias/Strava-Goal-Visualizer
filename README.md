# Strava Club Visualizer

A small Python project that syncs OAuth-authorized Strava run activities into SQLite and visualizes year-to-date progress toward a per-athlete goal (default: 365 km).

## Features

- OAuth-authorized athlete sync with pagination and retry handling
- SQLite cache with idempotent upserts
- Dashboard auto-sync when cached data is stale (default: 24 hours)
- Manual dashboard sync action: personal sync in default view, club sync in club view
- Athlete leaderboard showing progress toward 365 km
- Per-user annual goal preference (default 365 km) with saved override
- Year selector for dashboard analytics
- Interactive Jan-Dec cumulative yearly progress chart per athlete
- On-track guide line at 1 km/day for pace comparison
- Interactive web dashboard using Streamlit
- Dashboard privacy controls to disconnect an account and remove local data
- Dedicated Privacy Settings screen with identity verification before export/delete
- Strict quality tooling (ruff, mypy, pytest)

## Setup

1. Create and activate your virtual environment.
2. Install dependencies:

   pip install -r requirements.txt

3. Create your env file:

   copy .env.example .env

4. Configure auth in .env:

   Required:
   STRAVA_CLIENT_ID
   STRAVA_CLIENT_SECRET
   TOKEN_ENCRYPTION_KEY

   Generate TOKEN_ENCRYPTION_KEY with:

   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

## Usage

Authorize a Strava account via OAuth and store token locally:

python main.py oauth-authorize

Sync all authorized athletes:

python main.py sync-authorized

Sync one authorized athlete:

python main.py sync --verified-user-id 123456

List stored OAuth accounts:

python main.py oauth-list

Export one user's stored data (JSON):

python main.py export-user-data --verified-user-id 123456 --output exports/user_123456.json

Forget one user and delete local data:

python main.py forget-user --verified-user-id 123456

Preview inactive users (dry run):

python main.py cleanup-inactive --days 90

Execute inactive cleanup:

python main.py cleanup-inactive --days 90 --execute --revoke

Preview old activity cleanup (dry run):

python main.py cleanup-activities --years 3

Execute old activity cleanup:

python main.py cleanup-activities --years 3 --execute

List DSAR audit events:

python main.py list-dsar-events --limit 50

Launch dashboard:

python main.py dashboard

When using the dashboard:

- Connecting an account triggers an immediate sync for all authorized accounts.
- Opening the dashboard auto-syncs only when data is stale (configurable).
- In default view, `Sync yourself` syncs only your account and is rate-limited by
   `MANUAL_SYNC_COOLDOWN_SECONDS` (one hour by default).
- In club view (`?club_id=<id>`), `Sync club` syncs only connected members in that club.
   Cooldown is enforced per member, so recently synced members are skipped.
- If a user disconnects and deletes local data in `Privacy Settings`, that user is removed from
   future club sync account lists automatically.
- Annual goal defaults to `ANNUAL_GOAL_KM` (365 by default), and each user can save a custom goal.
- Custom goals are capped by `MAX_ANNUAL_GOAL_KM` (default: 100000).
- Privacy operations are available in `Privacy Settings` and require identity verification via
   Strava OAuth before data export or deletion.
- Disconnect in `Privacy Settings` revokes authorization and deletes all local data for the
   verified account in one action.

Or run Streamlit directly:

python -m streamlit run app/dashboard/dashboard_ui.py

## GitHub-Scheduled Maintenance (Render Free Tier)

If your hosting tier does not include built-in cron jobs, use the included GitHub workflow
`maintenance.yml` to trigger maintenance actions over HTTPS.

### 1. Configure app environment

Set `MAINTENANCE_CRON_TOKEN` in your deployed environment to a long random string.

### 2. Add GitHub repository secrets

Set these in GitHub: Settings -> Secrets and variables -> Actions -> New repository secret.

- `MAINTENANCE_BASE_URL`: your deployed app URL ending with `/`, for example
   `https://your-app-name.onrender.com/`
- `MAINTENANCE_CRON_TOKEN`: same value as your deployed `MAINTENANCE_CRON_TOKEN`

### 3. Enable scheduled workflow

The workflow file `.github/workflows/maintenance.yml` runs daily and can also be run manually via
Actions -> Scheduled Maintenance -> Run workflow.

It triggers:

- `cleanup-inactive` with `days=90`
- `cleanup-activities` with `years=3`

You can tune these values by editing `.github/workflows/maintenance.yml`.

## Deployment Guide

Automatic inactive-user cleanup does not schedule itself. The cleanup command exists in the app,
but a scheduler must run it in the target environment.

Recommended cleanup command:

python main.py cleanup-inactive --days 90 --execute --revoke

Recommended activity retention command:

python main.py cleanup-activities --years 3 --execute

### Step 1: Validate before automation

Run dry-run first and inspect output:

python main.py cleanup-inactive --days 90
python main.py cleanup-activities --years 3

Only after validating the output, enable --execute.

### Step 2: Choose scheduler by deployment target

1. Local Windows machine:
   Use Windows Task Scheduler to run the command daily (for example at 03:30).

2. Linux VM or dedicated server:
   Use cron/systemd timer to run the command daily.

3. Managed hosting / PaaS / container platform:
   Use a dedicated scheduled job or worker (platform cron feature). Do not rely on the web app
   process itself.

4. Serverless hosting:
   Use cloud scheduler that triggers a cleanup worker/job.

### Step 3: Production safety checks

- Ensure only one scheduler instance runs cleanup (avoid duplicate execution in multi-instance deployments).
- Log command output and monitor failures.
- Keep cleanup as a separate scheduled worker process, not tied to dashboard requests.
- Keep export/delete commands available for user data requests:

python main.py export-user-data --verified-user-id 123456 --output exports/user_123456.json
python main.py forget-user --verified-user-id 123456 --revoke

### Step 4: Go-live checklist

1. Dry-run output reviewed.
2. Scheduled job configured.
3. Logs confirmed after first automatic run.
4. Privacy policy and support contact published for user data requests.

## Quality Checks

ruff check .
mypy app
pytest

## Notes

- The app stores local data in data/strava_cache.db.
- Re-running sync updates existing activities and avoids duplicates.
- Sync is intentionally paced between pages to reduce API burst risk. Tune SYNC_PAGE_DELAY_SECONDS and SYNC_MAX_PAGES in .env if needed.
- Dashboard auto-sync policy can be tuned via AUTO_SYNC_ENABLED, AUTO_SYNC_STALENESS_HOURS, and MANUAL_SYNC_COOLDOWN_SECONDS.
- Sync progress is logged (page fetches, totals, and token refresh events). Set LOG_LEVEL in .env (for example INFO or DEBUG).
- Configure SUPPORT_CONTACT_EMAIL in .env so users can reach you for privacy/data requests.
- Data handling: the app stores OAuth account identity, token metadata, and synced activity records locally in SQLite for analytics.
- Inactivity cleanup: use `cleanup-inactive` regularly to remove inactive users and reduce retained personal data.
- Activity retention cleanup: use `cleanup-activities` to remove activity records older than your retention window.
- Data subject operations: use `export-user-data` for access/export requests and `forget-user` for delete requests.
- DSAR audit logging: export and delete actions are recorded in `dsar_audit_log` for compliance evidence.
- OAuth token secrets are encrypted at rest using `TOKEN_ENCRYPTION_KEY`.
- Scheduled maintenance trigger requests require `MAINTENANCE_CRON_TOKEN`.
- Keep .env private. The .gitignore already excludes it.
