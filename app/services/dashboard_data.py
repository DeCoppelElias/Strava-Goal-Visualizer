"""Dashboard data loading and view scope service.

Handles fetching activities, determining available years, and assembling
data for display views (personal vs club). Separated from UI layer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from app.storage.sqlite import SQLiteRepository


def available_years(
    repository: SQLiteRepository,
    *,
    verified_user_id: int | None = None,
    club_id: int | None = None,
) -> list[int]:
    """Get available activity years for the scope (personal or club view)."""
    years = repository.list_activity_years(
        verified_user_id=verified_user_id,
        club_id=club_id,
    )
    current_year = date.today().year
    if current_year not in years:
        years.append(current_year)
    return sorted(years, reverse=True)


def fetch_view_activities(
    repository: SQLiteRepository,
    *,
    year: int,
    verified_user_id: int | None = None,
    club_id: int | None = None,
) -> pd.DataFrame:
    """Fetch activities for the scope and year, with proper scope filtering."""
    year_start_utc = datetime(year, 1, 1, 0, 0, 0, tzinfo=UTC)
    year_end_utc = datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC)

    return repository.fetch_activities_df(
        start_date_utc=year_start_utc,
        end_date_utc=year_end_utc,
        verified_user_id=None if club_id is not None else verified_user_id,
        club_id=club_id,
    )


def fetch_view_goal_map(
    repository: SQLiteRepository,
    *,
    activities: pd.DataFrame,
    verified_user_id: int | None = None,
    club_id: int | None = None,
    default_goal_km: float = 365.0,
) -> dict[int, float] | float:
    """
    Fetch goal map for view scope.

    Returns single goal (float) for personal view or dict for club view.
    """
    if club_id is not None:
        # Club view: fetch individual goals for all athletes in activities
        club_athlete_ids = [int(value) for value in activities["athlete_id"].unique().tolist()]
        return repository.get_user_annual_goals(
            club_athlete_ids,
            default_goal_km=default_goal_km,
        )
    else:
        # Personal view: single goal
        if verified_user_id is None:
            return default_goal_km
        return repository.get_user_annual_goal(
            verified_user_id,
            default_goal_km=default_goal_km,
        )
