from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st

from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError

# Note: st.write/st.success output is only visible in a browser session via WebSocket.
# All maintenance results are also emitted via logger so they appear in server/Render logs.

logger = logging.getLogger(__name__)


def _query_param_int(key: str) -> int | None:
    raw = st.query_params.get(key)
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _query_param_text(key: str) -> str | None:
    raw = st.query_params.get(key)
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    value = str(raw).strip()
    return value if value else None


def _write_maintenance_error(message: str) -> None:
    logger.error("Maintenance error: %s", message)
    st.error(f"Maintenance error: {message}")


def handle_maintenance_request(settings: Any, repository: SQLiteRepository) -> bool:
    action = _query_param_text("maintenance_action")
    if action is None:
        return False

    provided_token = _query_param_text("maintenance_token")
    expected_token = settings.maintenance_cron_token
    if not expected_token:
        _write_maintenance_error("MAINTENANCE_CRON_TOKEN is not configured")
        return True
    if provided_token != expected_token:
        _write_maintenance_error("Invalid maintenance token")
        return True

    try:
        if action == "cleanup-inactive":
            days = _query_param_int("days") or 90
            cutoff = datetime.now(UTC) - timedelta(days=days)
            inactive_accounts = repository.list_inactive_oauth_accounts(cutoff)

            total_deleted_users = 0
            total_deleted_tokens = 0
            total_deleted_activities = 0
            for account in inactive_accounts:
                verified_user_id = account.get("verified_user_id")
                if not isinstance(verified_user_id, int):
                    continue
                deleted = repository.delete_verified_user_data(
                    verified_user_id,
                    delete_activities=True,
                )
                total_deleted_users += deleted["verified_users"]
                total_deleted_tokens += deleted["oauth_tokens"]
                total_deleted_activities += deleted["activities"]

            logger.info(
                "Maintenance cleanup-inactive complete: "
                "days=%d inactive=%d deleted_users=%d deleted_tokens=%d deleted_activities=%d",
                days,
                len(inactive_accounts),
                total_deleted_users,
                total_deleted_tokens,
                total_deleted_activities,
            )
            st.success(
                f"Cleanup inactive complete: {total_deleted_users} users removed "
                f"({len(inactive_accounts)} inactive, cutoff={days} days)."
            )
            return True

        if action == "cleanup-activities":
            years = _query_param_int("years") or 3
            cutoff = datetime.now(UTC) - timedelta(days=365 * years)
            old_count = repository.count_activities_older_than(cutoff)
            deleted = (
                repository.delete_activities_older_than(cutoff)
                if old_count > 0
                else {"activities": 0, "athletes": 0}
            )

            logger.info(
                "Maintenance cleanup-activities complete: "
                "years=%d older=%d deleted_activities=%d deleted_athletes=%d",
                years,
                old_count,
                deleted["activities"],
                deleted["athletes"],
            )
            st.success(
                f"Cleanup activities complete: {deleted['activities']} activities removed "
                f"({old_count} found older than {years} years)."
            )
            return True

        logger.warning("Unsupported maintenance_action: %s", action)
        _write_maintenance_error(f"Unsupported maintenance_action: {action}")
        return True
    except (StravaClientError, ValueError) as exc:
        logger.exception("Maintenance action failed: action=%s error=%s", action, exc)
        _write_maintenance_error(str(exc))
        return True
