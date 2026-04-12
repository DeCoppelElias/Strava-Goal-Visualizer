from __future__ import annotations

from math import isclose
from typing import Any

import streamlit as st

from app.storage.sqlite import SQLiteRepository


def render_goal_preference(
    settings: Any,
    repository: SQLiteRepository,
    *,
    viewer_user_id: int,
    inline: bool = False,
) -> None:
    ui = st if inline else st.sidebar
    key_prefix = "goal_pref_inline" if inline else "goal_pref_sidebar"

    current_goal_km = repository.get_user_annual_goal(
        viewer_user_id,
        default_goal_km=settings.annual_goal_km,
    )
    max_goal_km = float(settings.max_annual_goal_km)
    clamped_goal_km = min(max(float(current_goal_km), 1.0), max_goal_km)

    ui.subheader("Goal Preference")
    if isclose(float(current_goal_km), float(settings.annual_goal_km), rel_tol=0.0, abs_tol=1e-9):
        ui.caption("Original 365 Challenge")

    if not isclose(float(current_goal_km), clamped_goal_km, rel_tol=0.0, abs_tol=1e-9):
        ui.warning(
            "Saved goal is outside current limits and has been clamped in the input. "
            "Click Save Goal to persist the adjusted value."
        )

    goal_input_km = ui.number_input(
        "Your annual goal (km)",
        min_value=1.0,
        max_value=max_goal_km,
        value=clamped_goal_km,
        step=5.0,
        key=f"{key_prefix}_input",
    )
    if not isclose(float(goal_input_km), float(current_goal_km), rel_tol=0.0, abs_tol=1e-9):
        ui.caption("Unsaved goal change")

    if ui.button("Save Goal", key=f"{key_prefix}_save"):
        try:
            repository.update_user_annual_goal(
                viewer_user_id,
                float(goal_input_km),
                max_annual_goal_km=float(settings.max_annual_goal_km),
            )
            ui.success(f"Saved annual goal: {float(goal_input_km):.1f} km")
        except ValueError as exc:
            ui.error(f"Unable to save goal: {exc}")
