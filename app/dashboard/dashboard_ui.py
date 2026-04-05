from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import altair as alt
import streamlit as st

from app.config import load_settings
from app.dashboard.goal_preferences import render_goal_preference
from app.dashboard.privacy_settings import render_privacy_settings
from app.services.metrics import (
    athlete_progress_table,
    club_summary,
    cumulative_distance_progress,
    one_km_per_day_guide,
)
from app.services.oauth_auth import authorize_and_store_user
from app.services.sync import sync_all_authorized_users
from app.storage.sqlite import SQLiteRepository
from app.strava.client import StravaClientError
from app.strava.oauth import StravaOAuthError

_SESSION_VIEWER_KEY = "dashboard_verified_user_id"
_SESSION_PRIVACY_KEY = "privacy_verified_user_id"
_SESSION_VERIFIED_AT_KEY = "dashboard_verified_at_utc"
_SESSION_TIMEOUT = timedelta(minutes=15)


def _year_bounds_utc(year: int) -> tuple[datetime, datetime]:
    return (
        datetime(year, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
    )


def _available_years(
    repository: SQLiteRepository,
    *,
    verified_user_id: int | None = None,
    club_id: int | None = None,
) -> list[int]:
    years = repository.list_activity_years(
        verified_user_id=verified_user_id,
        club_id=club_id,
    )
    current_year = date.today().year
    if current_year not in years:
        years.append(current_year)
    return sorted(years, reverse=True)


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


def _short_athlete_name(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return full_name
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


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
                "completion_pct": "Completion (%)",
                "remaining_km": "Remaining (km)",
            }
        )
    )


def _parse_last_sync_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_sync_utc(oauth_accounts: list[dict[str, Any]]) -> datetime | None:
    latest: datetime | None = None
    for account in oauth_accounts:
        last_sync = _parse_last_sync_utc(account.get("last_sync_utc"))
        if last_sync is None:
            continue
        if latest is None or last_sync > latest:
            latest = last_sync
    return latest


def _any_account_stale(
    oauth_accounts: list[dict[str, Any]],
    *,
    now_utc: datetime,
    staleness_hours: int,
) -> bool:
    if not oauth_accounts:
        return False

    stale_before = now_utc - timedelta(hours=staleness_hours)
    for account in oauth_accounts:
        last_sync = _parse_last_sync_utc(account.get("last_sync_utc"))
        if last_sync is None or last_sync <= stale_before:
            return True
    return False


def _manual_sync_cooldown_remaining_seconds(
    latest_sync_utc: datetime | None,
    *,
    now_utc: datetime,
    cooldown_seconds: int,
) -> int:
    if latest_sync_utc is None:
        return 0

    elapsed_seconds = int((now_utc - latest_sync_utc).total_seconds())
    return max(0, cooldown_seconds - elapsed_seconds)


def _format_seconds(seconds: int) -> str:
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    hours, remaining_minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {remaining_minutes}m"
    if remaining_minutes > 0:
        return f"{remaining_minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def _mark_viewer_verified(verified_user_id: int) -> None:
    st.session_state[_SESSION_VIEWER_KEY] = verified_user_id
    st.session_state[_SESSION_PRIVACY_KEY] = verified_user_id
    st.session_state[_SESSION_VERIFIED_AT_KEY] = datetime.now(UTC).isoformat()


def _clear_viewer_session() -> None:
    st.session_state.pop(_SESSION_VIEWER_KEY, None)
    st.session_state.pop(_SESSION_PRIVACY_KEY, None)
    st.session_state.pop(_SESSION_VERIFIED_AT_KEY, None)


def _viewer_session_is_fresh(*, now_utc: datetime) -> bool:
    verified_at_raw = st.session_state.get(_SESSION_VERIFIED_AT_KEY)
    if not isinstance(verified_at_raw, str):
        return False
    try:
        verified_at = datetime.fromisoformat(verified_at_raw)
    except ValueError:
        return False
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    else:
        verified_at = verified_at.astimezone(UTC)
    return (now_utc - verified_at) <= _SESSION_TIMEOUT


def _run_sync(settings: Any, *, reason: str) -> bool:
    try:
        with st.spinner(reason):
            result = sync_all_authorized_users(settings)
    except (StravaClientError, ValueError) as exc:
        st.sidebar.warning(f"Sync failed, showing cached data: {exc}")
        return False

    if result.accounts_seen == 0:
        st.sidebar.info("No authorized accounts to sync yet.")
        return True

    st.sidebar.success(
        "Sync complete "
        f"({result.accounts_synced}/{result.accounts_seen} accounts, "
        f"stored {result.total_stored_activities} activities)."
    )
    return True


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

    years = _available_years(
        repository,
        verified_user_id=None if active_club_id is not None else viewer_user_id,
        club_id=active_club_id,
    )
    current_year = date.today().year
    default_year_index = years.index(current_year) if current_year in years else 0
    selected_year = st.selectbox("Year", options=years, index=default_year_index)

    year_start_utc, year_end_utc = _year_bounds_utc(selected_year)

    activities = repository.fetch_activities_df(
        start_date_utc=year_start_utc,
        end_date_utc=year_end_utc,
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

    if active_club_id is None:
        viewer_goal_km = repository.get_user_annual_goal(
            viewer_user_id,
            default_goal_km=settings.annual_goal_km,
        )
        guide_goal_km = viewer_goal_km
        progress = athlete_progress_table(activities, viewer_goal_km)
    else:
        club_athlete_ids = [int(value) for value in activities["athlete_id"].unique().tolist()]
        goal_map = repository.get_user_annual_goals(
            club_athlete_ids,
            default_goal_km=settings.annual_goal_km,
        )
        progress = athlete_progress_table(activities, goal_map)

    summary = club_summary(progress)
    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    if active_club_id is None:
        metric_col_1.metric("Your total distance", f"{summary.total_distance_km:.1f} km")
        metric_col_2.metric("Your goal distance", f"{summary.total_goal_km:.1f} km")
        metric_col_3.metric("Your completion", f"{summary.completion_pct:.1f}%")
        st.caption("Default view is private to your account.")
    else:
        metric_col_1.metric("Club total distance", f"{summary.total_distance_km:.1f} km")
        metric_col_2.metric("Club goal distance", f"{summary.total_goal_km:.1f} km")
        metric_col_3.metric("Club completion", f"{summary.completion_pct:.1f}%")
        st.caption(f"Viewing authorized members in club {active_club_id}.")

    st.subheader("Athlete progress")
    st.dataframe(_progress_display_table(progress), use_container_width=True, hide_index=True)

    st.subheader("Year progress (cumulative km)")
    cumulative = cumulative_distance_progress(activities)

    athlete_chart_data = cumulative.rename(
        columns={
            "athlete_name": "series",
            "cumulative_km": "km",
        }
    )[["date", "series", "km"]]

    guide_data = one_km_per_day_guide(
        selected_year,
        annual_goal_km=guide_goal_km,
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
    st.altair_chart(chart, use_container_width=True)


def run_dashboard() -> None:
    st.set_page_config(page_title="Strava Goal Tracker", layout="wide")
    st.title("Strava 365 km Goal Tracker")

    settings = load_settings()
    repository = SQLiteRepository(
        settings.database_path,
        token_encryption_key=settings.token_encryption_key,
    )
    repository.initialize()
    auto_sync_key = "dashboard_auto_sync_checked"
    viewer_key = _SESSION_VIEWER_KEY

    if st.sidebar.button("Log Out Viewer"):
        _clear_viewer_session()
        st.rerun()

    if st.session_state.get(viewer_key) is not None and not _viewer_session_is_fresh(
        now_utc=datetime.now(UTC)
    ):
        _clear_viewer_session()
        st.sidebar.info("Viewer session expired. Verify again to continue.")

    oauth_accounts = repository.get_oauth_accounts()
    latest_sync_utc = _latest_sync_utc(oauth_accounts)

    should_check_auto_sync = not st.session_state.get(auto_sync_key, False)
    if oauth_accounts and settings.auto_sync_enabled and should_check_auto_sync:
        if _any_account_stale(
            oauth_accounts,
            now_utc=datetime.now(UTC),
            staleness_hours=settings.auto_sync_staleness_hours,
        ):
            _run_sync(settings, reason="Auto-syncing stale account data...")
            oauth_accounts = repository.get_oauth_accounts()
            latest_sync_utc = _latest_sync_utc(oauth_accounts)
        st.session_state[auto_sync_key] = True

    st.sidebar.header("Verified Accounts")
    screen = st.sidebar.radio(
        "Screen",
        ["Dashboard", "Goal Preferences", "Privacy Settings"],
        index=0,
    )

    if st.sidebar.button("Connect Strava Account"):
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
            _run_sync(settings, reason="Syncing connected accounts...")
            oauth_accounts = repository.get_oauth_accounts()
            latest_sync_utc = _latest_sync_utc(oauth_accounts)
            st.session_state[auto_sync_key] = True
        except (StravaOAuthError, StravaClientError, TimeoutError, ValueError) as exc:
            st.sidebar.error(f"OAuth failed: {exc}")

    cooldown_remaining_seconds = _manual_sync_cooldown_remaining_seconds(
        latest_sync_utc,
        now_utc=datetime.now(UTC),
        cooldown_seconds=settings.manual_sync_cooldown_seconds,
    )

    if st.sidebar.button("Sync now", disabled=not oauth_accounts):
        if cooldown_remaining_seconds > 0:
            st.sidebar.info(
                "Sync cooldown active. Try again in "
                f"{_format_seconds(cooldown_remaining_seconds)}."
            )
        else:
            _run_sync(settings, reason="Syncing authorized accounts...")
            oauth_accounts = repository.get_oauth_accounts()
            latest_sync_utc = _latest_sync_utc(oauth_accounts)

    if oauth_accounts:
        if latest_sync_utc is None:
            st.sidebar.caption("Last sync: never")
        else:
            st.sidebar.caption(f"Last sync: {latest_sync_utc.strftime('%Y-%m-%d %H:%M UTC')}")
        if cooldown_remaining_seconds > 0:
            st.sidebar.caption(
                "Manual sync cooldown: " f"{_format_seconds(cooldown_remaining_seconds)} remaining"
            )
        for account in oauth_accounts:
            account_last_sync = _parse_last_sync_utc(account.get("last_sync_utc"))
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

    viewer_from_session = st.session_state.get(viewer_key)
    viewer_user_id = viewer_from_session if isinstance(viewer_from_session, int) else None
    valid_viewer_ids = {
        int(account["verified_user_id"])
        for account in oauth_accounts
        if isinstance(account.get("verified_user_id"), int)
    }
    if viewer_user_id not in valid_viewer_ids:
        viewer_user_id = None

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

    active_club_id = _query_param_int("club_id")
    _render_dashboard_main(
        settings,
        repository,
        viewer_user_id=viewer_user_id,
        active_club_id=active_club_id,
    )


if __name__ == "__main__":
    run_dashboard()
