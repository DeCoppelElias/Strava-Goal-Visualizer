from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def canonical_athlete_name(firstname: str | None, lastname: str | None) -> str:
    """Deterministic name for deduplication: lowercase, stripped, space-separated."""
    first = (firstname or "").strip().lower()
    last = (lastname or "").strip().lower()
    result = f"{first} {last}".strip()
    return result if result else "unknown"


def _stable_positive_int(seed: str) -> int:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    # Keep integer small enough for SQLite INTEGER + app usage.
    return int(digest[:15], 16)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ClubActivity:
    activity_id: int
    athlete_id: int
    athlete_name: str
    name: str
    distance_m: float
    moving_time_s: int
    elapsed_time_s: int
    elevation_gain_m: float
    sport_type: str
    start_date_utc: datetime
    raw_payload: dict[str, Any]

    @staticmethod
    def from_api_payload(payload: dict[str, Any]) -> ClubActivity:
        athlete = payload.get("athlete")
        athlete_dict = athlete if isinstance(athlete, dict) else {}
        athlete_id_raw = _coerce_int(athlete_dict.get("id"))

        first = str(athlete_dict.get("firstname") or "")
        last = str(athlete_dict.get("lastname") or "")
        combined_name = f"{first} {last}".strip()
        athlete_name = combined_name if combined_name else "Unknown Athlete"

        athlete_id = athlete_id_raw
        if athlete_id is None:
            athlete_id = _stable_positive_int(f"athlete:{athlete_name.lower()}")

        start_date = payload.get("start_date") or payload.get("start_date_local")
        if not start_date:
            raise ValueError("Activity payload is missing start_date")

        # Strava returns UTC dates as ISO-8601 with trailing Z.
        start_date_utc = datetime.fromisoformat(str(start_date).replace("Z", "+00:00"))

        activity_id_raw = _coerce_int(payload.get("id"))
        if activity_id_raw is None:
            synthetic_seed = (
                f"activity:{athlete_id}:{start_date_utc.isoformat()}:"
                f"{str(payload.get('name') or 'Unnamed activity').strip().lower()}"
            )
            activity_id_raw = _stable_positive_int(synthetic_seed)

        return ClubActivity(
            activity_id=activity_id_raw,
            athlete_id=athlete_id,
            athlete_name=athlete_name,
            name=str(payload.get("name", "Unnamed activity")),
            distance_m=float(payload.get("distance", 0.0)),
            moving_time_s=int(payload.get("moving_time", 0)),
            elapsed_time_s=int(payload.get("elapsed_time", 0)),
            elevation_gain_m=float(payload.get("total_elevation_gain", 0.0)),
            sport_type=str(payload.get("sport_type") or payload.get("type") or "Unknown"),
            start_date_utc=start_date_utc,
            raw_payload=payload,
        )
