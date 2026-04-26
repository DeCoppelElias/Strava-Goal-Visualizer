from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services.dashboard_data import (
    available_years,
    fetch_view_activities,
    fetch_view_goal_map,
)
from app.services.metrics import (
    athlete_progress_table,
    club_completion_summary,
    club_summary,
    cumulative_distance_progress,
    one_km_per_day_guide,
)
from app.storage.sqlite import SQLiteRepository

# =========================================================
# VIEW DATA
# =========================================================


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_available_years(
    _repository: SQLiteRepository, verified_user_id: int | None, club_id: int | None
) -> pd.DataFrame:
    return available_years(
        _repository,
        verified_user_id=verified_user_id,
        club_id=club_id,
    )


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_activities(
    _repository: SQLiteRepository, year: int, verified_user_id: int | None, club_id: int | None
) -> pd.DataFrame:
    return fetch_view_activities(
        _repository,
        year=year,
        verified_user_id=verified_user_id,
        club_id=club_id,
    )


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_goal_map(
    _repository: SQLiteRepository,
    activities: pd.DataFrame,
    verified_user_id: int | None,
    club_id: int | None,
    default_goal_km: float,
) -> pd.DataFrame:
    return fetch_view_goal_map(
        _repository,
        activities=activities,
        verified_user_id=verified_user_id,
        club_id=club_id,
        default_goal_km=default_goal_km,
    )


# =========================================================
# METRICS
# =========================================================


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_progress(
    activities: pd.DataFrame, goal_map: pd.DataFrame, selected_year: int
) -> pd.DataFrame:
    return athlete_progress_table(activities, goal_map, year=selected_year)


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_summary(progress: pd.DataFrame) -> pd.DataFrame:
    return club_summary(progress)


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_club_summary(progress: pd.DataFrame) -> pd.DataFrame:
    return club_completion_summary(progress)


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_cumulative(activities: pd.DataFrame) -> pd.DataFrame:
    return cumulative_distance_progress(activities)


@st.cache_data(ttl=300, show_spinner=False)  # type: ignore[misc]
def cached_guide(selected_year: int, goal_km: float) -> pd.DataFrame:
    return one_km_per_day_guide(selected_year, annual_goal_km=goal_km)
