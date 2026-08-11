import unittest
from typing import Optional, Dict
from app.modules.settings.domain.ports import SettingsRepositoryPort
from app.modules.settings.application.settings_service import SettingsService


class FakeSettingsRepository(SettingsRepositoryPort):
    def __init__(self):
        self.store: Dict[str, str] = {}

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.store.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.store[key] = value

    def get_all_settings(self) -> Dict[str, str]:
        return self.store.copy()


class TestSettingsService(unittest.TestCase):

    def test_get_default_model_settings(self):
        repo = FakeSettingsRepository()
        service = SettingsService(repo)
        settings = service.get_model_settings()

        self.assertIn(settings.model_load_mode, ("always", "idle"))
        self.assertGreater(settings.model_idle_timeout_sec, 0)

    def test_update_model_settings(self):
        repo = FakeSettingsRepository()
        service = SettingsService(repo)
        
        updated = service.update_model_settings(mode="idle", idle_timeout_sec=600.0)
        self.assertEqual(updated.model_load_mode, "idle")
        self.assertEqual(updated.model_idle_timeout_sec, 600.0)
        self.assertEqual(repo.get_setting("MODEL_LOAD_MODE"), "idle")
        self.assertEqual(repo.get_setting("MODEL_IDLE_TIMEOUT_SEC"), "600.0")


if __name__ == "__main__":
    unittest.main()
