from __future__ import annotations

from typing import Any


def build_activity_scope_clause(
    *,
    athlete_column: str,
    verified_user_id: int | None,
    club_id: int | None,
) -> tuple[str, list[Any]]:
    clause = ""
    params: list[Any] = []

    if verified_user_id is not None:
        clause += f" AND {athlete_column} = ?"
        params.append(verified_user_id)

    if club_id is not None:
        clause += (
            f" AND {athlete_column} IN ("
            "SELECT t.verified_user_id "
            "FROM oauth_tokens t "
            "JOIN verified_user_clubs c ON c.verified_user_id = t.verified_user_id "
            "WHERE c.club_id = ? "
            "UNION "
            "SELECT l.club_athlete_id "
            "FROM athlete_identity_links l "
            "JOIN oauth_tokens t ON t.verified_user_id = l.verified_user_id "
            "JOIN verified_user_clubs c ON c.verified_user_id = t.verified_user_id "
            "WHERE c.club_id = ?"
            ")"
        )
        params.extend([club_id, club_id])

    return clause, params
