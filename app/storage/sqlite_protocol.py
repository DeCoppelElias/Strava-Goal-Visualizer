from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol


class SQLiteRepositoryProtocol(Protocol):
    _db_path: Path

    def _connect(self) -> sqlite3.Connection: ...

    def _encrypt_token(self, token: str | None) -> str | None: ...

    def _decrypt_token(self, token: str | None) -> str | None: ...

    def _column_exists(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
    ) -> bool: ...
