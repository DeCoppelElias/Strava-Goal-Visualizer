from __future__ import annotations

import json
from pathlib import Path

from app.cli.context import CommandContext
from app.services.account_lifecycle import revoke_account_if_requested


def export_user_data_command(ctx: CommandContext) -> int:
    verified_user_id = ctx.args.verified_user_id
    output = ctx.args.output

    payload = ctx.repository.export_verified_user_data(verified_user_id)
    if payload is None:
        print(f"No verified user found for id={verified_user_id}.")
        return 1

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ctx.repository.log_dsar_event(
        verified_user_id=verified_user_id,
        event_type="export",
        request_source="cli",
        details={"result": "written", "output_path": str(output_path)},
    )

    print(
        "User data export complete. "
        f"verified_user_id={verified_user_id} "
        f"activities={len(payload.get('activities', []))} "
        f"path={output_path}"
    )
    return 0


def forget_user_command(ctx: CommandContext) -> int:
    verified_user_id = ctx.args.verified_user_id
    revoke = ctx.args.revoke
    keep_activities = ctx.args.keep_activities

    account = ctx.repository.get_oauth_account_by_verified_user_id(verified_user_id)
    if account is None:
        print(f"No OAuth account found for verified_user_id={verified_user_id}.")
        return 1

    ctx.repository.log_dsar_event(
        verified_user_id=verified_user_id,
        event_type="erasure",
        request_source="cli",
        details={"result": "requested", "keep_activities": keep_activities},
    )

    revoked, revoke_error = revoke_account_if_requested(
        ctx.settings,
        account,
        revoke=revoke,
    )
    if not revoked:
        print(f"Warning: could not revoke Strava token before delete: {revoke_error}")

    deleted = ctx.repository.delete_verified_user_data(
        verified_user_id,
        delete_activities=not keep_activities,
    )
    ctx.repository.log_dsar_event(
        verified_user_id=None,
        event_type="erasure",
        request_source="cli",
        details={
            "result": "completed",
            "deleted": deleted,
            "deleted_verified_user_id": verified_user_id,
        },
    )
    print(
        "User data removal complete. "
        f"verified_users={deleted['verified_users']} "
        f"oauth_tokens={deleted['oauth_tokens']} "
        f"activities={deleted['activities']} "
        f"athletes={deleted['athletes']}"
    )
    return 0
