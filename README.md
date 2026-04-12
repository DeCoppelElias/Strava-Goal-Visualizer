# Goal Visualizer

A privacy-first analytics dashboard that syncs OAuth-authorized Strava run activities into SQLite and visualizes year-to-date progress toward a per-athlete goal (default: 365 km).

## Features

- **OAuth Integration** — Secure Strava account authorization with pagination and automatic retry handling.
- **SQLite Analytics** — Local-first data storage with intelligent caching and deduplication.
- **Smart Sync** — Auto-sync when stale (24h default) plus on-demand sync with per-user cooldown.
- **Club Leaderboards** — View multiple athletes' yearly progress toward goal in one dashboard.
- **Customizable Goals** — Per-athlete annual goal with visual progress tracking (goal/365 km/day guide line).
- **Privacy Controls** — Identity-verified data export and deletion, account disconnection, audit logging.
- **Interactive Charts** — Jan-Dec cumulative progress, year selector, multi-athlete comparison.
- **Quality & Testing** — Full type hints (mypy), code style (ruff), and pytest test suite.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Virtual environment tool (venv or conda)

### 2. Installation

```bash
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# or: source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy template
copy .env.example .env  # Windows
# or: cp .env.example .env  # macOS/Linux
```

Edit `.env` and set required fields:
```dotenv
STRAVA_CLIENT_ID=your_app_id
STRAVA_CLIENT_SECRET=your_app_secret
TOKEN_ENCRYPTION_KEY=<generated below>
```

Generate an encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. Launch Dashboard

```bash
python main.py dashboard
```

Visit `http://localhost:8501` in your browser. Authorize your Strava account via OAuth.

## CLI Commands

### Strava OAuth
```bash
# Authorize a new Strava account
python main.py oauth-authorize

# List all authorized accounts
python main.py oauth-list
```

### Syncing Activities
```bash
# Sync all authorized athletes
python main.py sync-authorized

# Sync one athlete by ID
python main.py sync --verified-user-id 123456
```

### Data Export & Deletion
```bash
# Export one user's data as JSON
python main.py export-user-data --verified-user-id 123456 --output exports/user_123456.json

# Delete one user's stored data and revoke OAuth
python main.py forget-user --verified-user-id 123456
```

### Maintenance & Cleanup

Dry-run (preview without changes):
```bash
# Preview inactive users (inactivity > 90 days)
python main.py cleanup-inactive --days 90

# Preview old activities (older than 3 years)
python main.py cleanup-activities --years 3
```

Execute cleanup:
```bash
# Remove inactive users and revoke their OAuth tokens
python main.py cleanup-inactive --days 90 --execute --revoke

# Delete old activities
python main.py cleanup-activities --years 3 --execute
```

### Audit & Monitoring
```bash
# View DSAR (Data Subject Access Request) audit log
python main.py list-dsar-events --limit 50

# Launch Streamlit directly (alternative to 'dashboard' command)
python -m streamlit run app/dashboard/dashboard_ui.py
```

## Dashboard Usage

### Behavior & Features
- **Connecting an account** triggers an immediate sync for all authorized accounts.
- **Auto-sync** only triggers when data is stale (configurable via `AUTO_SYNC_STALENESS_HOURS`, default 24h).
- **Personal sync** (`Sync yourself` in default view) syncs only your account and respects `MANUAL_SYNC_COOLDOWN_SECONDS` (1h default).
- **Club sync** (`Sync club` in club view with `?club_id=<id>`) syncs all connected members; cooldown is per-member.
- **Custom goals** — Each athlete can set a custom annual goal (capped by `MAX_ANNUAL_GOAL_KM`, default 100,000 km).
- **Year-to-date progress** — View cumulative km toward goal with interactive charts and pace guide.
- **Privacy Settings** — Access data export, deletion, and account disconnection (all require OAuth re-verification).

### Authentication Note
Users who disconnect and delete data in Privacy Settings are automatically removed from future club sync lists.

## Maintenance & Scheduling

Cleanup operations must be scheduled to run regularly. Choose one:

### Option 1: GitHub Actions (Recommended for Render)
The included `.github/workflows/maintenance.yml` automatically runs daily and can also be triggered manually.
It triggers both cleanup jobs:
- `cleanup-inactive` with a 90-day inactivity window
- `cleanup-activities` with a 3-year retention window

**Setup:**
1. Set `MAINTENANCE_CRON_TOKEN` in your deployed environment to a random string.
2. Add these as GitHub repository secrets:
  - `MAINTENANCE_BASE_URL`: your app URL only, with no query string (e.g., `https://your-app.onrender.com`)
   - `MAINTENANCE_CRON_TOKEN`: same value as above
3. Commit and push; workflow runs automatically each day.

Edit the workflow to customize cleanup frequency (default: 90-day inactivity, 3-year activity retention).

### Option 2: Manual / Local Scheduler
For development or self-hosted deployments, run cleanup commands on a schedule:

```bash
# Daily via Windows Task Scheduler, Linux cron, or platform-specific scheduler
python main.py cleanup-inactive --days 90 --execute --revoke
python main.py cleanup-activities --years 3 --execute
```

Always dry-run first to verify output before enabling `--execute`.

## GitHub Pages Legal Documentation

This repository includes public legal pages in the `docs/` folder:
- `docs/index.html` — Home page with app overview
- `docs/about.html` — Feature description and technical details
- `docs/privacy.html` — Privacy policy
- `docs/terms.html` — Terms of service
- `docs/data-deletion.html` — Data deletion instructions

These are automatically published to GitHub Pages. Configure in repository Settings → Pages:
- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/docs`

Use the published URLs in your Strava app settings and dashboard configuration (see `.env.example`).

## Development

### Code Quality

Run all checks:
```bash
ruff check .          # Lint
ruff format .         # Auto-format
mypy app              # Type checking
pytest                # Run tests
```

Pre-commit hooks run automatically on `git commit` (same checks as above).

### Project Structure
```
app/
  config.py           # Settings & environment variables
  dashboard/          # Streamlit UI components
  services/           # Sync & metrics logic
  storage/            # SQLite repositories & encryption
  strava/             # Strava API client
docs/                 # GitHub Pages legal site
tests/                # Test suite
```

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE).
