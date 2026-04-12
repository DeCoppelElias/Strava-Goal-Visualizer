from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from app.services.account_lifecycle import revoke_account_if_requested
from app.services.oauth_auth import authorize_and_store_user
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError
from app.strava.oauth import StravaOAuthError


def _legal_links(settings: Any) -> None:
    st.markdown("### Public legal pages")

    about_url = str(getattr(settings, "about_url", "") or "").strip()
    policy_url = str(getattr(settings, "privacy_policy_url", "") or "").strip()
    terms_url = str(getattr(settings, "terms_url", "") or "").strip()
    deletion_url = str(getattr(settings, "data_deletion_url", "") or "").strip()

    has_all_links = bool(policy_url and terms_url and deletion_url)
    if not has_all_links:
        st.info(
            "Set PRIVACY_POLICY_URL, TERMS_URL, and DATA_DELETION_URL in your environment "
            "to publish external legal links here."
        )

    col_about, col_policy, col_terms, col_deletion = st.columns(4)
    with col_about:
        if about_url:
            st.link_button("About this app", about_url, use_container_width=True)
    with col_policy:
        if policy_url:
            st.link_button("Privacy policy", policy_url, use_container_width=True)
    with col_terms:
        if terms_url:
            st.link_button("Terms", terms_url, use_container_width=True)
    with col_deletion:
        if deletion_url:
            st.link_button("Data deletion", deletion_url, use_container_width=True)


def _privacy_policy_notice(settings: Any) -> None:
    st.markdown("## Privacy Settings")
    st.caption(
        "Control your data lifecycle here: verify identity, export your data, and permanently "
        "disconnect your account with full local data removal."
    )
    st.caption(
        "We store your Strava profile, OAuth tokens, and synced activity data solely for "
        "dashboard analytics. You can export or delete your data below at any time. "
        "See the linked pages for the full privacy policy and terms."
    )
    _legal_links(settings)

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
    # Check session timeout (15 minutes between verifications)
    _SESSION_TIMEOUT = timedelta(minutes=15)
    _SESSION_VERIFIED_AT_KEY = "dashboard_verified_at_utc"

    verified_at_str = st.session_state.get(_SESSION_VERIFIED_AT_KEY)
    if verified_at_str:
        try:
            verified_at_dt = datetime.fromisoformat(verified_at_str)
            age = datetime.now(UTC) - verified_at_dt
            if age > _SESSION_TIMEOUT:
                st.warning(
                    f"⏱️ Session expired after {_SESSION_TIMEOUT.total_seconds() / 60:.0f} minutes. "
                    "Please verify your identity again."
                )
                clear_viewer_session()
                st.stop()
        except (ValueError, TypeError):
            pass  # Invalid timestamp format, continue

    _privacy_policy_notice(settings)

    export_json = "{}"
    export_file_name = "strava_user_export.json"
    can_download = False
    verified_user_id_for_log: int | None = None

    # Check if in deployed web mode with OAuth state persistence
    _oauth_pending_url_key = "privacy_oauth_pending_authorize_url"
    pending_authorize_url = st.session_state.get(_oauth_pending_url_key)

    if settings.app_base_url and not pending_authorize_url:
        # Web redirect flow (deployed)
        if st.button("Verify My Identity With Strava", use_container_width=True):
            try:
                from app.services.oauth_auth import begin_oauth_flow

                authorize_url = begin_oauth_flow(settings, repository)
                st.session_state[_oauth_pending_url_key] = authorize_url
                st.rerun()
            except (ValueError, StravaOAuthError) as exc:
                st.error(f"OAuth setup failed: {exc}")
    elif pending_authorize_url:
        # Web redirect pending
        st.info(
            "Opening Strava authorization in a new tab. "
            "If nothing opens, click the button below."
        )
        st.link_button(
            "✓ Open Strava Authorization",
            pending_authorize_url,
            type="primary",
            use_container_width=True,
        )
        # Try desktop auto-redirect (works on desktop, harmless on mobile).
        components.html(
            f"""
            <script>
            try {{
              window.location.href = {pending_authorize_url!r};
            }} catch(e) {{
              console.log('Auto-redirect unavailable, use button above.');
            }}
            </script>
            """,
            height=0,
        )
    else:
        # Local server flow (local dev / CLI)
        if st.button("Verify My Identity With Strava", use_container_width=True):
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
