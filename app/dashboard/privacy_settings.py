from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import streamlit as st

from app.services.account_lifecycle import revoke_account_if_requested
from app.services.oauth_auth import authorize_and_store_user
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError
from app.strava.oauth import StravaOAuthError


def _privacy_policy_notice(settings: Any) -> None:
    st.markdown("## Privacy Settings")
    st.caption(
        "Control your data lifecycle here: verify identity, export your data, and permanently "
        "disconnect your account with full local data removal."
    )
    st.markdown(
        """
### Privacy Notice

- We store your Strava profile identifiers, OAuth token metadata, and synced activity data in a
  local SQLite database to provide dashboard analytics.
- We use this data only to sync your runs and render your progress views.
- You can export your stored data from this screen at any time.
- You can permanently remove your account data from this app from this screen at any time.
- Inactive accounts can be cleaned up automatically by the app operator based on retention policy.
        """
    )
    if settings.support_contact_email:
        st.markdown(f"Support contact: {settings.support_contact_email}")
    else:
        st.warning("Support contact email is not configured. Set SUPPORT_CONTACT_EMAIL in .env.")


def _disconnect_and_delete_user(
    settings: Any,
    repository: SQLiteRepository,
    *,
    verified_user_id: int,
) -> tuple[dict[str, int], str | None]:
    revoke_warning: str | None = None

    account = repository.get_oauth_account_by_verified_user_id(verified_user_id)
    if account is not None:
        revoked, revoke_error = revoke_account_if_requested(
            settings,
            account,
            revoke=True,
        )
        if not revoked:
            revoke_warning = revoke_error

    deleted = repository.delete_verified_user_data(
        verified_user_id,
        delete_activities=True,
    )
    return deleted, revoke_warning


def render_privacy_settings(
    settings: Any,
    repository: SQLiteRepository,
    *,
    has_any_account: bool,
    identity_key: str,
    mark_viewer_verified: Callable[[int], None],
    clear_viewer_session: Callable[[], None],
) -> None:
    _privacy_policy_notice(settings)

    export_json = "{}"
    export_file_name = "strava_user_export.json"
    can_download = False
    verified_user_id_for_log: int | None = None

    if st.button("Verify My Identity With Strava"):
        try:
            with st.spinner("Waiting for Strava OAuth callback..."):
                user = authorize_and_store_user(
                    settings,
                    repository,
                    open_browser_window=True,
                )
            mark_viewer_verified(user.verified_user_id)
            st.success(
                "Identity verified as "
                f"{user.firstname} {user.lastname} (id={user.verified_user_id})."
            )
        except (StravaOAuthError, StravaClientError, TimeoutError, ValueError) as exc:
            st.error(f"Identity verification failed: {exc}")

    verified_user_id = st.session_state.get(identity_key)
    account: dict[str, Any] | None = None
    if not isinstance(verified_user_id, int):
        st.caption("Verify identity to enable export and delete actions.")
    else:
        verified_user_id_for_log = verified_user_id
        account = repository.get_oauth_account_by_verified_user_id(verified_user_id)
        if account is None:
            st.caption(
                "No local account found for the verified identity. Connect your account first, "
                "then verify again."
            )
        else:
            st.success(
                "Authenticated account: "
                f"{account['firstname']} {account['lastname']} (id={account['verified_user_id']})"
            )

            exported = repository.export_verified_user_data(verified_user_id)
            if exported is not None:
                export_json = json.dumps(exported, indent=2)
                export_file_name = f"strava_user_{verified_user_id}_export.json"
                can_download = True

    if (
        st.download_button(
            "Download My Data (JSON)",
            data=export_json,
            file_name=export_file_name,
            mime="application/json",
            disabled=not can_download,
            help=(
                "Verify your identity with Strava first to enable download."
                if not can_download
                else ""
            ),
        )
        and verified_user_id_for_log is not None
    ):
        repository.log_dsar_event(
            verified_user_id=verified_user_id_for_log,
            event_type="export",
            request_source="dashboard",
            details={"result": "downloaded"},
        )

    delete_user_id = verified_user_id if isinstance(verified_user_id, int) else None
    can_delete = account is not None and delete_user_id is not None

    st.caption(
        "Disconnecting will revoke Strava authorization and permanently delete your local account, "
        "token, and synced activities in this app."
    )
    if st.button(
        "Disconnect & Delete Everything",
        disabled=not can_delete,
        help="Verify your identity first to enable deletion." if not can_delete else "",
    ):
        if delete_user_id is None:
            st.error("Unable to determine the verified account to delete. Verify again and retry.")
        else:
            safe_user_id = delete_user_id
            repository.log_dsar_event(
                verified_user_id=safe_user_id,
                event_type="erasure",
                request_source="dashboard",
                details={"result": "requested"},
            )
            deleted, revoke_warning = _disconnect_and_delete_user(
                settings,
                repository,
                verified_user_id=safe_user_id,
            )
            repository.log_dsar_event(
                verified_user_id=None,
                event_type="erasure",
                request_source="dashboard",
                details={
                    "result": "completed",
                    "deleted": deleted,
                    "deleted_verified_user_id": safe_user_id,
                },
            )
            if revoke_warning is not None:
                st.warning("Strava revoke failed, but local data was removed: " f"{revoke_warning}")
            st.success(
                "Account disconnected. "
                f"Removed users={deleted['verified_users']} "
                f"tokens={deleted['oauth_tokens']} "
                f"activities={deleted['activities']}."
            )
            clear_viewer_session()
            st.rerun()

    if not has_any_account:
        st.info("No connected accounts remain in local storage.")
