"""
SQLite adapter implementing SettingsRepositoryPort.
"""

from typing import Optional, Dict
from app.core.db import get_db_connection
from app.modules.settings.domain.ports import SettingsRepositoryPort


class SQLiteSettingsRepository(SettingsRepositoryPort):
    """SQLite outbound adapter for settings storage."""

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row["value"]
        return default

    def set_setting(self, key: str, value: str) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            return {r["key"]: r["value"] for r in cursor.fetchall()}
