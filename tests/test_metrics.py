from __future__ import annotations

import pandas as pd

from app.services.metrics import (
    athlete_progress_table,
    club_summary,
    cumulative_distance_progress,
    one_km_per_day_guide,
)


def test_athlete_progress_table_calculates_goal_progress() -> None:
    df = pd.DataFrame(
        [
            {
                "activity_id": 1,
                "athlete_id": 10,
                "athlete_name": "Runner A",
                "distance_m": 10000.0,
                "start_date_utc": "2026-01-10T08:00:00+00:00",
            },
            {
                "activity_id": 2,
                "athlete_id": 10,
                "athlete_name": "Runner A",
                "distance_m": 5000.0,
                "start_date_utc": "2026-01-12T08:00:00+00:00",
            },
            {
                "activity_id": 3,
                "athlete_id": 20,
                "athlete_name": "Runner B",
                "distance_m": 21097.5,
                "start_date_utc": "2026-01-15T08:00:00+00:00",
            },
        ]
    )

    progress = athlete_progress_table(df, annual_goal_km=365.0)

    runner_a = progress.loc[progress["athlete_id"] == 10].iloc[0]
    assert runner_a["run_count"] == 2
    assert round(float(runner_a["distance_km"]), 2) == 15.0
    assert round(float(runner_a["remaining_km"]), 2) == 350.0


def test_athlete_progress_table_supports_per_athlete_goal_map() -> None:
    df = pd.DataFrame(
        [
            {
                "activity_id": 1,
                "athlete_id": 10,
                "athlete_name": "Runner A",
                "distance_m": 20000.0,
                "start_date_utc": "2026-01-10T08:00:00+00:00",
            },
            {
                "activity_id": 2,
                "athlete_id": 20,
                "athlete_name": "Runner B",
                "distance_m": 25000.0,
                "start_date_utc": "2026-01-11T08:00:00+00:00",
            },
        ]
    )

    progress = athlete_progress_table(df, annual_goal_km={10: 500.0, 20: 400.0})

    runner_a = progress.loc[progress["athlete_id"] == 10].iloc[0]
    runner_b = progress.loc[progress["athlete_id"] == 20].iloc[0]
    assert float(runner_a["goal_km"]) == 500.0
    assert float(runner_b["goal_km"]) == 400.0
    assert round(float(runner_a["completion_pct"]), 2) == 4.0
    assert round(float(runner_b["completion_pct"]), 2) == 6.25


def test_club_summary_aggregates_totals() -> None:
    progress = pd.DataFrame(
        [
            {"athlete_id": 1, "distance_km": 100.0, "goal_km": 365.0},
            {"athlete_id": 2, "distance_km": 50.0, "goal_km": 365.0},
        ]
    )

    summary = club_summary(progress)

    assert round(summary.total_distance_km, 2) == 150.0
    assert round(summary.total_goal_km, 2) == 730.0
    assert round(summary.completion_pct, 2) == round((150.0 / 730.0) * 100.0, 2)


def test_cumulative_distance_progress_builds_running_totals() -> None:
    activities = pd.DataFrame(
        [
            {
                "activity_id": 1,
                "athlete_name": "Runner A",
                "distance_m": 5000.0,
                "start_date_utc": "2026-01-01T08:00:00+00:00",
            },
            {
                "activity_id": 2,
                "athlete_name": "Runner A",
                "distance_m": 10000.0,
                "start_date_utc": "2026-01-03T08:00:00+00:00",
            },
        ]
    )

    cumulative = cumulative_distance_progress(activities)

    assert len(cumulative) == 2
    assert round(float(cumulative.iloc[0]["cumulative_km"]), 2) == 5.0
    assert round(float(cumulative.iloc[1]["cumulative_km"]), 2) == 15.0


def test_cumulative_distance_progress_keeps_athletes_separate() -> None:
    activities = pd.DataFrame(
        [
            {
                "activity_id": 1,
                "athlete_name": "Runner A",
                "distance_m": 10000.0,
                "start_date_utc": "2026-01-01T08:00:00+00:00",
            },
            {
                "activity_id": 2,
                "athlete_name": "Runner B",
                "distance_m": 5000.0,
                "start_date_utc": "2026-01-02T08:00:00+00:00",
            },
            {
                "activity_id": 3,
                "athlete_name": "Runner B",
                "distance_m": 7000.0,
                "start_date_utc": "2026-01-03T08:00:00+00:00",
            },
        ]
    )

    cumulative = cumulative_distance_progress(activities)

    runner_b = cumulative[cumulative["athlete_name"] == "Runner B"].reset_index(drop=True)
    assert round(float(runner_b.iloc[0]["cumulative_km"]), 2) == 5.0
    assert round(float(runner_b.iloc[1]["cumulative_km"]), 2) == 12.0


def test_one_km_per_day_guide_has_day_200_at_200_km() -> None:
    guide = one_km_per_day_guide(2026)

    assert len(guide) == 365
    assert int(guide.iloc[199]["guide_km"]) == 200
    assert int(round(float(guide.iloc[-1]["guide_km"]))) == 365


def test_one_km_per_day_guide_matches_leap_year_length() -> None:
    guide = one_km_per_day_guide(2024)

    assert len(guide) == 366
    assert int(round(float(guide.iloc[-1]["guide_km"]))) == 365


def test_one_km_per_day_guide_scales_to_custom_goal() -> None:
    guide = one_km_per_day_guide(2026, annual_goal_km=730.0)

    assert len(guide) == 365
    assert int(round(float(guide.iloc[199]["guide_km"]))) == 400
    assert int(round(float(guide.iloc[-1]["guide_km"]))) == 730
