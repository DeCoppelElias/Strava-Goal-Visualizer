from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    strava_client_id: int
    strava_client_secret: str
    annual_goal_km: float = 365.0
    max_annual_goal_km: float = 100000.0
    database_path: Path = Path("data/strava_cache.db")
    sync_page_size: int = 100
    sync_page_delay_seconds: float = 1.1
    sync_max_pages: int = 60
    request_timeout_seconds: int = 20
    auto_sync_enabled: bool = True
    auto_sync_staleness_hours: int = 24
    manual_sync_cooldown_seconds: int = 3600
    support_contact_email: str = ""
    token_encryption_key: str = ""
    maintenance_cron_token: str = ""
    app_base_url: str = ""
    privacy_policy_url: str = ""
    terms_url: str = ""
    data_deletion_url: str = ""
    about_url: str = ""


def load_settings() -> Settings:
    load_dotenv()

    page_size = int(os.getenv("SYNC_PAGE_SIZE", "100"))
    if page_size < 1 or page_size > 200:
        raise ValueError("SYNC_PAGE_SIZE must be between 1 and 200")

    page_delay_seconds = float(os.getenv("SYNC_PAGE_DELAY_SECONDS", "1.1"))
    if page_delay_seconds < 0:
        raise ValueError("SYNC_PAGE_DELAY_SECONDS must be >= 0")

    sync_max_pages = int(os.getenv("SYNC_MAX_PAGES", "60"))
    if sync_max_pages < 1:
        raise ValueError("SYNC_MAX_PAGES must be >= 1")

    auto_sync_enabled = os.getenv("AUTO_SYNC_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    auto_sync_staleness_hours = int(os.getenv("AUTO_SYNC_STALENESS_HOURS", "24"))
    if auto_sync_staleness_hours < 1:
        raise ValueError("AUTO_SYNC_STALENESS_HOURS must be >= 1")

    manual_sync_cooldown_seconds = int(os.getenv("MANUAL_SYNC_COOLDOWN_SECONDS", "3600"))
    if manual_sync_cooldown_seconds < 0:
        raise ValueError("MANUAL_SYNC_COOLDOWN_SECONDS must be >= 0")

    annual_goal_km = float(os.getenv("ANNUAL_GOAL_KM", "365"))
    if annual_goal_km <= 0:
        raise ValueError("ANNUAL_GOAL_KM must be > 0")

    max_annual_goal_km = float(os.getenv("MAX_ANNUAL_GOAL_KM", "100000"))
    if max_annual_goal_km <= 0:
        raise ValueError("MAX_ANNUAL_GOAL_KM must be > 0")
    if annual_goal_km > max_annual_goal_km:
        raise ValueError("ANNUAL_GOAL_KM must be <= MAX_ANNUAL_GOAL_KM")

    client_id_raw = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    token_encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()

    if not client_id_raw or not client_secret:
        raise ValueError("Authorized-only mode requires STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET")
    if not token_encryption_key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY is required. Generate with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )

    return Settings(
        strava_client_id=int(client_id_raw),
        strava_client_secret=client_secret,
        annual_goal_km=annual_goal_km,
        max_annual_goal_km=max_annual_goal_km,
        database_path=Path(os.getenv("DATABASE_PATH", "data/strava_cache.db")),
        sync_page_size=page_size,
        sync_page_delay_seconds=page_delay_seconds,
        sync_max_pages=sync_max_pages,
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        auto_sync_enabled=auto_sync_enabled,
        auto_sync_staleness_hours=auto_sync_staleness_hours,
        manual_sync_cooldown_seconds=manual_sync_cooldown_seconds,
        support_contact_email=os.getenv("SUPPORT_CONTACT_EMAIL", "").strip(),
        token_encryption_key=token_encryption_key,
        maintenance_cron_token=os.getenv("MAINTENANCE_CRON_TOKEN", "").strip(),
        app_base_url=os.getenv(
            "APP_BASE_URL",
            os.getenv("RENDER_EXTERNAL_URL", ""),
        )
        .strip()
        .rstrip("/"),
        privacy_policy_url=os.getenv("PRIVACY_POLICY_URL", "").strip(),
        terms_url=os.getenv("TERMS_URL", "").strip(),
        data_deletion_url=os.getenv("DATA_DELETION_URL", "").strip(),
        about_url=os.getenv("ABOUT_URL", "").strip(),
    )
