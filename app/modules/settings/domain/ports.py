"""
Settings domain ports (interfaces).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict


class SettingsRepositoryPort(ABC):
    """Port for reading and persisting runtime key-value settings."""
    
    @abstractmethod
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Reads a setting value by key, returning default if absent."""
        pass

    @abstractmethod
    def set_setting(self, key: str, value: str) -> None:
        """Upserts a setting key-value pair."""
        pass

    @abstractmethod
    def get_all_settings(self) -> Dict[str, str]:
        """Returns all settings as a dictionary."""
        pass
