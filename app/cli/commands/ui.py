from __future__ import annotations

import subprocess
import sys

from app.cli.context import CommandContext


def dashboard_command(_: CommandContext) -> int:
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", "app/dashboard/dashboard_ui.py"]
    )
