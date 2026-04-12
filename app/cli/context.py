from __future__ import annotations

import argparse
from dataclasses import dataclass

from app.config import Settings, load_settings
from app.storage.sqlite import SQLiteRepository


@dataclass(slots=True)
class CommandContext:
    args: argparse.Namespace
    _settings: Settings | None = None
    _repository: SQLiteRepository | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings()
        return self._settings

    @property
    def repository(self) -> SQLiteRepository:
        if self._repository is None:
            self._repository = SQLiteRepository(
                self.settings.database_path,
                token_encryption_key=self.settings.token_encryption_key,
            )
            self._repository.initialize()
        return self._repository
