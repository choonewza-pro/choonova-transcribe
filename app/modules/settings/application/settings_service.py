"""
Application Service for managing runtime model settings.
"""

from app.core.config import MODEL_LOAD_MODE_DEFAULT, MODEL_IDLE_TIMEOUT_SEC_DEFAULT
from app.modules.settings.domain.entities import ModelSettings
from app.modules.settings.domain.ports import SettingsRepositoryPort


class SettingsService:
    """Orchestrates runtime setting read/write use cases."""

    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

    def get_model_settings(self) -> ModelSettings:
        mode = self.repo.get_setting("MODEL_LOAD_MODE", MODEL_LOAD_MODE_DEFAULT) or "always"
        timeout_raw = self.repo.get_setting("MODEL_IDLE_TIMEOUT_SEC", str(MODEL_IDLE_TIMEOUT_SEC_DEFAULT))
        try:
            timeout = float(timeout_raw) if timeout_raw else MODEL_IDLE_TIMEOUT_SEC_DEFAULT
        except ValueError:
            timeout = MODEL_IDLE_TIMEOUT_SEC_DEFAULT

        return ModelSettings(
            model_load_mode=mode,
            model_idle_timeout_sec=timeout,
        )

    def update_model_settings(self, mode: str | None = None, idle_timeout_sec: float | None = None) -> ModelSettings:
        if mode is not None:
            clean_mode = mode.strip().lower()
            if clean_mode in ("always", "idle"):
                self.repo.set_setting("MODEL_LOAD_MODE", clean_mode)

        if idle_timeout_sec is not None and idle_timeout_sec >= 0:
            self.repo.set_setting("MODEL_IDLE_TIMEOUT_SEC", str(idle_timeout_sec))

        return self.get_model_settings()
