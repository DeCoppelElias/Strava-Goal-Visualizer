from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import altair as alt
import streamlit as st

from app.config import load_settings
from app.dashboard.dashboard_cache import (
    cached_activities,
    cached_available_years,
    cached_club_summary,
    cached_cumulative,
    cached_goal_map,
    cached_guide,
    cached_progress,
    cached_summary,
)
from app.dashboard.goal_preferences import render_goal_preference
from app.dashboard.privacy_settings import render_privacy_settings
from app.maintenance.runner import handle_maintenance_request
from app.services import oauth_auth
from app.services.dashboard_sync import (
    account_last_sync_utc,
    latest_sync_utc,
    manual_sync_cooldown_remaining_seconds,
    run_sync_for_club_members,
    run_sync_for_viewer,
)
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError
from app.strava.oauth import StravaOAuthError

_SESSION_VIEWER_KEY = "dashboard_verified_user_id"
_SESSION_PRIVACY_KEY = "privacy_verified_user_id"
_SESSION_OAUTH_PENDING_URL_KEY = "oauth_pending_authorize_url"
_SESSION_PRIVACY_OAUTH_PENDING_URL_KEY = "privacy_oauth_pending_authorize_url"
_SESSION_POST_OAUTH_CLUB_ID_KEY = "post_oauth_club_id"


def _clear_pending_oauth_urls() -> None:
    st.session_state.pop(_SESSION_OAUTH_PENDING_URL_KEY, None)
    st.session_state.pop(_SESSION_PRIVACY_OAUTH_PENDING_URL_KEY, None)


def _apply_post_oauth_navigation() -> None:
    post_oauth_club_id = st.session_state.pop(_SESSION_POST_OAUTH_CLUB_ID_KEY, None)
    st.query_params.clear()
    if isinstance(post_oauth_club_id, int) and post_oauth_club_id > 0:
        st.query_params["club_id"] = str(post_oauth_club_id)


@dataclass
class _DashboardAccountContext:
    oauth_accounts: list[dict[str, Any]]
    latest_sync_utc_val: datetime | None
    viewer_user_id: int | None
    viewer_last_sync_utc: datetime | None


def _refresh_account_sync_times(
    repository: SQLiteRepository,
    *,
    oauth_accounts: list[dict[str, Any]],
    viewer_user_id: int | None,
) -> tuple[list[dict[str, Any]], datetime | None, datetime | None]:
    refreshed_accounts = repository.get_oauth_accounts()
    latest_sync_utc_val = latest_sync_utc(refreshed_accounts)
    viewer_last_sync_utc = (
        account_last_sync_utc(refreshed_accounts, viewer_user_id)
        if viewer_user_id is not None
        else None
    )
    return refreshed_accounts, latest_sync_utc_val, viewer_last_sync_utc


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


def _short_athlete_name(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return full_name
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


def _format_seconds(seconds: int) -> str:
    """Format seconds into human-readable duration (e.g., '1h 30m')."""
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    hours, remaining_minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {remaining_minutes}m"
    if remaining_minutes > 0:
        return f"{remaining_minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def _progress_display_table(progress: Any) -> Any:
    return (
        progress.assign(
            athlete=lambda df: df["athlete_name"].map(_short_athlete_name),
            distance_km=lambda df: df["distance_km"].round(2),
            goal_km=lambda df: df["goal_km"].round(2),
            completion_pct=lambda df: df["completion_pct"].round(2),
            remaining_km=lambda df: df["remaining_km"].round(2),
        )
        .loc[
            :,
            [
                "athlete",
                "run_count",
                "distance_km",
                "goal_km",
                "days_elapsed",
                "completion_pct",
                "remaining_km",
            ],
        ]
        .rename(
            columns={
                "athlete": "Athlete",
                "run_count": "Runs",
                "distance_km": "Distance (km)",
                "goal_km": "Goal (km)",
                "days_elapsed": "Days",
                "completion_pct": "Completion (%)",
                "remaining_km": "Remaining (km)",
            }
        )
    )


def _mark_viewer_verified(verified_user_id: int) -> None:
    st.session_state[_SESSION_VIEWER_KEY] = verified_user_id
    st.session_state[_SESSION_PRIVACY_KEY] = verified_user_id


def _clear_viewer_session() -> None:
    st.session_state.pop(_SESSION_VIEWER_KEY, None)
    st.session_state.pop(_SESSION_PRIVACY_KEY, None)


def _load_account_context(repository: SQLiteRepository, *, viewer_key: str) -> _DashboardAccountContext:
    oauth_accounts = repository.get_oauth_accounts()
    latest_sync_utc_val = latest_sync_utc(oauth_accounts)
    viewer_from_session = st.session_state.get(viewer_key)
    viewer_user_id = viewer_from_session if isinstance(viewer_from_session, int) else None
    valid_viewer_ids = {
        int(account["verified_user_id"])
        for account in oauth_accounts
        if isinstance(account.get("verified_user_id"), int)
    }
    if viewer_user_id not in valid_viewer_ids:
        viewer_user_id = None
    viewer_last_sync_utc = (
        account_last_sync_utc(oauth_accounts, viewer_user_id)
        if viewer_user_id is not None
        else None
    )
    return _DashboardAccountContext(
        oauth_accounts=oauth_accounts,
        latest_sync_utc_val=latest_sync_utc_val,
        viewer_user_id=viewer_user_id,
        viewer_last_sync_utc=viewer_last_sync_utc,
    )


def _handle_oauth_query_callback(settings: Any, repository: SQLiteRepository) -> bool:
    # Detect Strava OAuth callback error from query params.
    oauth_error = _query_param_text("error")
    if oauth_error:
        st.query_params.clear()
        st.error(f"Strava authorization was not completed: {oauth_error}")
        return True

    # Detect Strava OAuth web callback (code + state in URL after redirect).
    oauth_code = _query_param_text("code")
    oauth_state = _query_param_text("state")
    if not (oauth_code and oauth_state):
        return False

    complete_oauth_flow = getattr(oauth_auth, "complete_oauth_flow", None)
    if not callable(complete_oauth_flow):
        st.query_params.clear()
        st.error(
            "OAuth callback handler is unavailable in this build. "
            "Please redeploy or restart the app."
        )
        return True
    try:
        user = complete_oauth_flow(settings, repository, oauth_code, oauth_state)
        _mark_viewer_verified(user.verified_user_id)
        st.session_state.pop(_SESSION_OAUTH_PENDING_URL_KEY, None)
        st.query_params.clear()
        st.rerun()
    except (StravaOAuthError, StravaClientError, ValueError) as exc:
        st.session_state.pop(_SESSION_OAUTH_PENDING_URL_KEY, None)
        st.query_params.clear()
        st.error(f"Strava authorization failed: {exc}")
    return True


def _render_connected_accounts_sidebar(
    *,
    oauth_accounts: list[dict[str, Any]],
    viewer_user_id: int | None,
    viewer_last_sync_utc: datetime | None,
    latest_sync_utc_val: datetime | None,
    active_club_id: int | None,
    cooldown_remaining_seconds: int,
    manual_sync_cooldown_seconds: int,
) -> None:
    if oauth_accounts:
        if viewer_user_id is not None and viewer_last_sync_utc is None:
            st.sidebar.caption("Your last sync: never")
        elif viewer_user_id is not None and viewer_last_sync_utc is not None:
            st.sidebar.caption(
                f"Your last sync: {viewer_last_sync_utc.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        elif latest_sync_utc_val is None:
            st.sidebar.caption("Last sync: never")
        else:
            st.sidebar.caption(f"Last sync: {latest_sync_utc_val.strftime('%Y-%m-%d %H:%M UTC')}")
        if active_club_id is None and cooldown_remaining_seconds > 0:
            st.sidebar.caption(
                "Manual sync cooldown: " f"{_format_seconds(cooldown_remaining_seconds)} remaining"
            )
        if active_club_id is not None:
            st.sidebar.caption(
                "Club sync uses per-member cooldowns "
                f"({manual_sync_cooldown_seconds}s each)."
            )
        for account in oauth_accounts:
            account_last_sync = parse_last_sync_utc(account.get("last_sync_utc"))
            account_last_sync_text = (
                account_last_sync.strftime("%Y-%m-%d %H:%M UTC")
                if account_last_sync is not None
                else "never"
            )
            st.sidebar.caption(
                f"{account['firstname']} {account['lastname']} "
                f"(id={account['verified_user_id']}, last sync: {account_last_sync_text})"
            )
    else:
        st.sidebar.caption("No connected accounts yet")
        st.sidebar.caption("Connect accounts to sync and visualize data")


def _render_dashboard_main(
    settings: Any,
    repository: SQLiteRepository,
    *,
    viewer_user_id: int,
    active_club_id: int | None,
) -> None:
    guide_goal_km = settings.annual_goal_km
    if active_club_id is not None and not repository.is_verified_user_in_club(
        viewer_user_id,
        active_club_id,
    ):
        st.error("You are not authorized to view this club leaderboard.")
        return

    years = cached_available_years(
        repository,
        verified_user_id=None if active_club_id is not None else viewer_user_id,
        club_id=active_club_id,
    )
    current_year = date.today().year
    default_year_index = years.index(current_year) if current_year in years else 0
    selected_year = st.selectbox("Year", options=years, index=default_year_index)

    activities = cached_activities(
        repository,
        year=selected_year,
        verified_user_id=None if active_club_id is not None else viewer_user_id,
        club_id=active_club_id,
    )

    if activities.empty:
        if active_club_id is None:
            st.info(f"No activities found for {selected_year}. Run a sync first.")
        else:
            st.info(
                f"No authorized club activities found for club {active_club_id} in {selected_year}."
            )
        return

    goal_map = cached_goal_map(
        repository,
        activities=activities,
        verified_user_id=None if active_club_id is not None else viewer_user_id,
        club_id=active_club_id,
        default_goal_km=settings.annual_goal_km,
    )

    if active_club_id is None:
        # Personal view: goal_map is a single float
        guide_goal_km = goal_map if isinstance(goal_map, float) else settings.annual_goal_km
        progress = cached_progress(activities, guide_goal_km, selected_year)
    else:
        # Club view: goal_map is a dict
        progress = cached_progress(
            activities,
            goal_map if isinstance(goal_map, dict) else settings.annual_goal_km,
            selected_year,
        )

    summary = cached_summary(progress)
    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    if active_club_id is None:
        metric_col_1.metric("Your total distance", f"{summary.total_distance_km:.1f} km")
        metric_col_2.metric("Your goal distance", f"{summary.total_goal_km:.1f} km")
        metric_col_3.metric("Your completion", f"{summary.completion_pct:.1f}%")
        st.caption("Default view is private to your account.")
    else:
        club_progress = cached_club_summary(progress)
        metric_col_1.metric("Athletes tracked", f"{club_progress.athlete_count}")
        metric_col_2.metric("Avg completion", f"{club_progress.average_completion_pct:.1f}%")
        metric_col_3.metric(
            "At or above goal",
            f"{club_progress.athletes_at_goal}/{club_progress.athlete_count}",
        )
        st.caption(f"Viewing authorized members in club {active_club_id}.")

    st.subheader("Athlete progress")
    st.dataframe(_progress_display_table(progress), width="stretch", hide_index=True)

    st.subheader("Year progress (cumulative km)")
    cumulative = cached_cumulative(activities)

    athlete_chart_data = cumulative.rename(
        columns={
            "athlete_name": "series",
            "cumulative_km": "km",
        }
    )[["date", "series", "km"]]

    guide_data = cached_guide(
        selected_year,
        goal_km=guide_goal_km,
    ).rename(columns={"guide_km": "km"})
    guide_data["series"] = f"On-track guide ({guide_goal_km:.0f} km goal)"

    x_domain = [
        datetime(selected_year, 1, 1),
        datetime(selected_year, 12, 31, 23, 59, 59),
    ]

    x_encoding = alt.X(
        "date:T",
        title=f"{selected_year} (Jan-Dec)",
        scale=alt.Scale(domain=x_domain),
    )
    y_encoding = alt.Y("km:Q", title="Cumulative distance (km)")

    athlete_lines = (
        alt.Chart(athlete_chart_data)
        .mark_line(point=True)
        .encode(
            x=x_encoding,
            y=y_encoding,
            color=alt.Color("series:N", title="Athlete"),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("series:N", title="Athlete"),
                alt.Tooltip("km:Q", title="Cumulative km", format=".2f"),
            ],
        )
    )

    guide_line = (
        alt.Chart(guide_data)
        .mark_line(color="#6b7280", strokeDash=[6, 6], strokeWidth=2)
        .encode(
            x=x_encoding,
            y=y_encoding,
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("km:Q", title="On-track km", format=".0f"),
            ],
        )
    )

    chart = (athlete_lines + guide_line).properties(height=420)
    st.altair_chart(chart, width="stretch")


def run_dashboard() -> None:
    st.set_page_config(page_title="Strava Goal Tracker", layout="wide")

    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()

    if handle_maintenance_request(settings, repository):
        return

    oauth_callback_error_message: str | None = None

    # Detect Strava OAuth callback error from query params.
    oauth_error = _query_param_text("error")
    if oauth_error:
        _clear_pending_oauth_urls()
        _apply_post_oauth_navigation()
        oauth_callback_error_message = f"Strava authorization was not completed: {oauth_error}"

    # Detect Strava OAuth web callback (code + state in URL after redirect).
    oauth_code = _query_param_text("code")
    oauth_state = _query_param_text("state")
    oauth_scope = _query_param_text("scope")
    if oauth_code and oauth_state:
        complete_oauth_flow = getattr(oauth_auth, "complete_oauth_flow", None)
        if not callable(complete_oauth_flow):
            _apply_post_oauth_navigation()
            oauth_callback_error_message = (
                "OAuth callback handler is unavailable in this build. "
                "Please redeploy or restart the app."
            )
        else:
            try:
                user = complete_oauth_flow(
                    settings,
                    repository,
                    oauth_code,
                    oauth_state,
                    granted_scope=oauth_scope,
                )
                _mark_viewer_verified(user.verified_user_id)
                _clear_pending_oauth_urls()
                _apply_post_oauth_navigation()
                st.rerun()
            except (StravaOAuthError, StravaClientError, ValueError) as exc:
                _clear_pending_oauth_urls()
                _apply_post_oauth_navigation()
                oauth_callback_error_message = f"Strava authorization failed: {exc}"

    st.title("Strava Goal Tracker")
    if oauth_callback_error_message:
        st.error(oauth_callback_error_message)

    auto_sync_key = "dashboard_auto_sync_checked"
    viewer_key = _SESSION_VIEWER_KEY

    oauth_accounts = repository.get_oauth_accounts()
    latest_sync_utc_val = latest_sync_utc(oauth_accounts)
    viewer_from_session = st.session_state.get(viewer_key)
    viewer_user_id = viewer_from_session if isinstance(viewer_from_session, int) else None
    valid_viewer_ids = {
        int(account["verified_user_id"])
        for account in oauth_accounts
        if isinstance(account.get("verified_user_id"), int)
    }
    if viewer_user_id not in valid_viewer_ids:
        viewer_user_id = None
    if viewer_user_id is None and len(oauth_accounts) == 1:
        only_account = oauth_accounts[0]
        only_verified_user_id = only_account.get("verified_user_id")
        if isinstance(only_verified_user_id, int):
            _mark_viewer_verified(only_verified_user_id)
            viewer_user_id = only_verified_user_id
    viewer_last_sync_utc = (
        account_last_sync_utc(oauth_accounts, viewer_user_id)
        if viewer_user_id is not None
        else None
    )

    should_check_auto_sync = not st.session_state.get(auto_sync_key, False)
    if oauth_accounts and settings.auto_sync_enabled and should_check_auto_sync:
        auto_sync_completed = False
        if viewer_user_id is not None:
            stale_before = datetime.now(UTC) - timedelta(hours=settings.auto_sync_staleness_hours)
            if viewer_last_sync_utc is None or viewer_last_sync_utc <= stale_before:
                auto_sync_completed = run_sync_for_viewer(
                    settings,
                    verified_user_id=viewer_user_id,
                    reason="Auto-syncing your stale account data...",
                )
                if auto_sync_completed:
                    oauth_accounts, latest_sync_utc_val, viewer_last_sync_utc = (
                        _refresh_account_sync_times(
                            repository,
                            oauth_accounts=oauth_accounts,
                            viewer_user_id=viewer_user_id,
                        )
                    )
            else:
                auto_sync_completed = True

        if auto_sync_completed:
            st.session_state[auto_sync_key] = True

    st.sidebar.header("Verified Accounts")
    screen = st.sidebar.radio(
        "Screen",
        ["Dashboard", "Goal Preferences", "Privacy Settings"],
        index=0,
    )
    active_club_id = _query_param_int("club_id")

    if settings.app_base_url:
        # Web redirect flow (deployed)
        if st.sidebar.button("Connect Strava Account"):
            begin_oauth_flow = getattr(oauth_auth, "begin_oauth_flow", None)
            if not callable(begin_oauth_flow):
                st.sidebar.error(
                    "OAuth setup is unavailable in this build. "
                    "Please redeploy or restart the app."
                )
                return
            try:
                authorize_url = begin_oauth_flow(settings, repository)
                st.session_state[_SESSION_POST_OAUTH_CLUB_ID_KEY] = active_club_id
                st.session_state[_SESSION_OAUTH_PENDING_URL_KEY] = authorize_url
                st.rerun()
            except (ValueError, StravaOAuthError) as exc:
                st.sidebar.error(f"OAuth setup failed: {exc}")

        pending_authorize_url = st.session_state.get(_SESSION_OAUTH_PENDING_URL_KEY)
        if isinstance(pending_authorize_url, str) and pending_authorize_url:
            st.sidebar.info(
                "Continue authorization in this same tab to ensure "
                "the callback updates this session."
            )
            st.sidebar.markdown(
                f'<a href="{pending_authorize_url}" target="_self">'
                "Continue OAuth in this tab"
                "</a>",
                unsafe_allow_html=True,
            )
            st.sidebar.link_button(
                "Open Strava Authorization (new tab)",
                pending_authorize_url,
                width="stretch",
            )
            if st.sidebar.button("I completed authorization"):
                _clear_pending_oauth_urls()
                st.rerun()
            if st.sidebar.button("Start authorization over"):
                _clear_pending_oauth_urls()
                st.rerun()
    else:
        # Local server flow (local dev / CLI)
        if st.sidebar.button("Connect Strava Account"):
            authorize_and_store_user = getattr(oauth_auth, "authorize_and_store_user", None)
            if not callable(authorize_and_store_user):
                st.sidebar.error(
                    "Local OAuth flow is unavailable in this build. "
                    "Please redeploy or restart the app."
                )
                return
            try:
                with st.spinner("Waiting for Strava OAuth callback..."):
                    user = authorize_and_store_user(
                        settings,
                        repository,
                        open_browser_window=True,
                    )
                st.sidebar.success(
                    f"Connected {user.firstname} {user.lastname} (id={user.verified_user_id})"
                )
                _mark_viewer_verified(user.verified_user_id)
                sync_completed = run_sync_for_viewer(
                    settings,
                    verified_user_id=user.verified_user_id,
                    reason="Syncing your account...",
                )
                if sync_completed:
                    oauth_accounts, latest_sync_utc_val, viewer_last_sync_utc = (
                        _refresh_account_sync_times(
                            repository,
                            oauth_accounts=oauth_accounts,
                            viewer_user_id=user.verified_user_id,
                        )
                    )
                    viewer_user_id = user.verified_user_id
                    st.session_state[auto_sync_key] = True
                    st.rerun()
            except (StravaOAuthError, StravaClientError, TimeoutError, ValueError) as exc:
                st.sidebar.error(f"OAuth failed: {exc}")

    sync_reference_utc = viewer_last_sync_utc if viewer_user_id is not None else latest_sync_utc_val
    cooldown_remaining_seconds = manual_sync_cooldown_remaining_seconds(
        sync_reference_utc,
        now_utc=datetime.now(UTC),
        cooldown_seconds=settings.manual_sync_cooldown_seconds,
    )

    viewer_in_active_club = (
        active_club_id is not None
        and viewer_user_id is not None
        and repository.is_verified_user_in_club(viewer_user_id, active_club_id)
    )
    sync_button_label = "Sync club" if active_club_id is not None else "Sync yourself"
    sync_disabled = viewer_user_id is None or (
        active_club_id is not None and not viewer_in_active_club
    )

    if st.sidebar.button(sync_button_label, disabled=sync_disabled):
        if viewer_user_id is None:
            st.sidebar.info("Verify your viewer identity before syncing.")
            return
        if active_club_id is not None:
            if not viewer_in_active_club:
                st.sidebar.warning("You are not authorized to sync this club.")
                return
            club_accounts = repository.list_oauth_accounts_in_club(active_club_id)
            if not club_accounts:
                st.sidebar.info(
                    "No connected members found in this club. "
                    "Ask members to connect their Strava account first."
                )
            else:
                run_sync_for_club_members(
                    settings,
                    club_id=active_club_id,
                    club_accounts=club_accounts,
                )
                oauth_accounts, latest_sync_utc_val, viewer_last_sync_utc = _refresh_account_sync_times(
                    repository,
                    oauth_accounts=oauth_accounts,
                    viewer_user_id=viewer_user_id,
                )
        else:
            if cooldown_remaining_seconds > 0:
                st.sidebar.info(
                    "Sync cooldown active. Try again in "
                    f"{_format_seconds(cooldown_remaining_seconds)}."
                )
            else:
                run_sync_for_viewer(
                    settings,
                    verified_user_id=viewer_user_id,
                    reason="Syncing your account...",
                )
                oauth_accounts, latest_sync_utc_val, viewer_last_sync_utc = _refresh_account_sync_times(
                    repository,
                    oauth_accounts=oauth_accounts,
                    viewer_user_id=viewer_user_id,
                )

    if oauth_accounts:
        account_count = len(oauth_accounts)
        st.sidebar.caption(f"{account_count} account{'s' if account_count != 1 else ''} connected")
        if viewer_user_id is not None and viewer_last_sync_utc is None:
            st.sidebar.caption("Your last sync: never")
        elif viewer_user_id is not None and viewer_last_sync_utc is not None:
            st.sidebar.caption(
                f"Your last sync: {viewer_last_sync_utc.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        elif latest_sync_utc_val is None:
            st.sidebar.caption("Last sync: never")
        else:
            st.sidebar.caption(f"Last sync: {latest_sync_utc_val.strftime('%Y-%m-%d %H:%M UTC')}")
        if active_club_id is None and cooldown_remaining_seconds > 0:
            st.sidebar.caption(
                "Manual sync cooldown: " f"{_format_seconds(cooldown_remaining_seconds)} remaining"
            )
        if active_club_id is not None:
            st.sidebar.caption(
                "Club sync uses per-member cooldowns "
                f"({settings.manual_sync_cooldown_seconds}s each)."
            )
    else:
        st.sidebar.caption("No connected accounts yet")
        st.sidebar.caption("Connect accounts to sync and visualize data")

    # Sidebar footer with links to public site pages
    about_url = getattr(settings, "about_url", "") or ""
    privacy_policy_url = getattr(settings, "privacy_policy_url", "") or ""
    if about_url or privacy_policy_url:
        st.sidebar.markdown("---")
        parts = []
        if about_url:
            parts.append(f"[About Goal Visualizer]({about_url})")
        if privacy_policy_url:
            parts.append(f"[Privacy]({privacy_policy_url})")
        st.sidebar.caption(" · ".join(parts))

    if screen == "Privacy Settings":
        render_privacy_settings(
            settings,
            repository,
            has_any_account=bool(oauth_accounts),
            identity_key=_SESSION_PRIVACY_KEY,
            mark_viewer_verified=_mark_viewer_verified,
            clear_viewer_session=_clear_viewer_session,
        )
        return

    if viewer_user_id is None:
        st.info(
            "Verify your viewer identity by connecting your Strava account "
            "before opening the dashboard."
        )
        return

    if screen == "Goal Preferences":
        render_goal_preference(
            settings,
            repository,
            viewer_user_id=viewer_user_id,
            inline=True,
        )
        return

    _render_dashboard_main(
        settings,
        repository,
        viewer_user_id=viewer_user_id,
        active_club_id=active_club_id,
    )


if __name__ == "__main__":
    run_dashboard()
