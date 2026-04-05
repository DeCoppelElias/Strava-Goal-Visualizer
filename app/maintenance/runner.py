from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st

from app.services.sync import sync_all_authorized_users
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError

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
    st.error("MAINTENANCE_STATUS=error")
    st.write(f"reason={message}")


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
        if action == "sync-authorized":
            result = sync_all_authorized_users(settings)
            st.success("MAINTENANCE_STATUS=ok")
            st.write("action=sync-authorized")
            st.write(f"accounts_seen={result.accounts_seen}")
            st.write(f"accounts_synced={result.accounts_synced}")
            st.write(f"stored_activities={result.total_stored_activities}")
            return True

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

            st.success("MAINTENANCE_STATUS=ok")
            st.write("action=cleanup-inactive")
            st.write(f"days={days}")
            st.write(f"inactive_accounts={len(inactive_accounts)}")
            st.write(f"deleted_verified_users={total_deleted_users}")
            st.write(f"deleted_oauth_tokens={total_deleted_tokens}")
            st.write(f"deleted_activities={total_deleted_activities}")
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

            st.success("MAINTENANCE_STATUS=ok")
            st.write("action=cleanup-activities")
            st.write(f"years={years}")
            st.write(f"older_activities={old_count}")
            st.write(f"deleted_activities={deleted['activities']}")
            st.write(f"deleted_orphan_athletes={deleted['athletes']}")
            return True

        _write_maintenance_error(f"Unsupported maintenance_action: {action}")
        return True
    except (StravaClientError, ValueError) as exc:
        logger.exception("Maintenance action failed: %s", action)
        _write_maintenance_error(str(exc))
        return True
