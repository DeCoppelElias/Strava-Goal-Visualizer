from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ClubSummary:
    total_distance_km: float
    total_goal_km: float
    completion_pct: float



def athlete_progress_table(
    activities: pd.DataFrame,
    annual_goal_km: float | Mapping[int, float],
) -> pd.DataFrame:
    if activities.empty:
        return pd.DataFrame(
            columns=[
                "athlete_id",
                "athlete_name",
                "run_count",
                "distance_km",
                "goal_km",
                "completion_pct",
                "remaining_km",
            ]
        )

    grouped = (
        activities.groupby(["athlete_id", "athlete_name"], as_index=False)
        .agg(
            run_count=("activity_id", "count"),
            distance_m=("distance_m", "sum"),
        )
        .assign(distance_km=lambda df: df["distance_m"] / 1000.0)
    )

    if isinstance(annual_goal_km, Mapping):
        grouped["goal_km"] = grouped["athlete_id"].map(
            lambda athlete_id: float(annual_goal_km.get(int(athlete_id), 365.0))
        )
    else:
        grouped["goal_km"] = float(annual_goal_km)

    grouped["completion_pct"] = (grouped["distance_km"] / grouped["goal_km"]) * 100.0
    grouped["remaining_km"] = (grouped["goal_km"] - grouped["distance_km"]).clip(lower=0.0)

    return grouped[
        [
            "athlete_id",
            "athlete_name",
            "run_count",
            "distance_km",
            "goal_km",
            "completion_pct",
            "remaining_km",
        ]
    ].sort_values(by=["completion_pct", "distance_km"], ascending=False)



def club_summary(progress_table: pd.DataFrame) -> ClubSummary:
    if progress_table.empty:
        return ClubSummary(total_distance_km=0.0, total_goal_km=0.0, completion_pct=0.0)

    total_distance = float(progress_table["distance_km"].sum())
    total_goal = float(progress_table["goal_km"].sum())
    completion = 0.0 if total_goal == 0.0 else (total_distance / total_goal) * 100.0

    return ClubSummary(
        total_distance_km=total_distance,
        total_goal_km=total_goal,
        completion_pct=completion,
    )



def cumulative_distance_progress(activities: pd.DataFrame) -> pd.DataFrame:
    if activities.empty:
        return pd.DataFrame(columns=["date", "athlete_name", "cumulative_km"])

    df = activities.copy()
    df["start_date_utc"] = pd.to_datetime(df["start_date_utc"], utc=True)
    df["date"] = (
        df["start_date_utc"]
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .dt.normalize()
    )

    daily = (
        df.groupby(["athlete_name", "date"], as_index=False)
        .agg(distance_m=("distance_m", "sum"))
        .sort_values(["athlete_name", "date"])
    )
    daily["cumulative_km"] = daily.groupby("athlete_name")["distance_m"].cumsum() / 1000.0

    return daily[["date", "athlete_name", "cumulative_km"]]


def one_km_per_day_guide(year: int, annual_goal_km: float = 365.0) -> pd.DataFrame:
    dates = pd.date_range(
        start=f"{year}-01-01",
        end=f"{year}-12-31",
        freq="D",
    )
    day_count = len(dates)
    daily_target_km = 0.0 if day_count == 0 else float(annual_goal_km) / float(day_count)
    return pd.DataFrame(
        {
            "date": dates,
            "guide_km": pd.Series(
                [daily_target_km * float(day + 1) for day in range(day_count)],
                dtype="float64",
            ),
        }
    )
