"""
SQLite adapter implementing SelfTestStatusRepository.

Persists only pass/fail + timestamps for each self-test card and suite, so the
verification state survives a plain server restart. The build fingerprint is
kept in the `self_test_meta` table so a NEW build (changed deployed code) can
reset all statuses to "not tested".

Tables (all created lazily, idempotent):
- self_test_status:      per-card verdicts, PK (suite, test_order)
- self_test_suite_status: aggregate verdict per suite, PK (suite)
- self_test_meta:         key/value store (build_stamp)
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from app.core.db import get_db_connection
from app.modules.apitest.domain.entities import SelfTestStatus
from app.modules.apitest.domain.ports import SelfTestStatusRepository


class SQLiteSelfTestStatusRepository(SelfTestStatusRepository):
    """SQLite outbound adapter for self-test pass/fail status."""

    def __init__(self, conn_factory=get_db_connection):
        self._conn_factory = conn_factory

    # ------------------------------------------------------------- internal

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_table(self) -> None:
        with self._conn_factory() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_test_status (
                    suite TEXT NOT NULL,
                    test_order INTEGER NOT NULL,
                    test_label TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'not_tested',
                    updated_at TEXT,
                    PRIMARY KEY (suite, test_order)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_test_suite_status (
                    suite TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_test_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            conn.commit()

    # ------------------------------------------------------------- per-card

    def upsert_test(self, suite: str, test_order: int, test_label: str,
                    status: str) -> None:
        self._ensure_table()
        with self._conn_factory() as conn:
            conn.execute(
                """
                INSERT INTO self_test_status (suite, test_order, test_label, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(suite, test_order) DO UPDATE SET
                    test_label = excluded.test_label,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (suite, test_order, test_label, status, self._now_iso()),
            )
            conn.commit()

    def get_tests(self, suite: str) -> Dict[int, SelfTestStatus]:
        self._ensure_table()
        with self._conn_factory() as conn:
            rows = conn.execute(
                "SELECT * FROM self_test_status WHERE suite = ? ORDER BY test_order",
                (suite,),
            ).fetchall()
        out: Dict[int, SelfTestStatus] = {}
        for r in rows:
            out[r["test_order"]] = SelfTestStatus(
                suite=r["suite"],
                status=r["status"],
                test_order=r["test_order"],
                test_label=r["test_label"],
                updated_at=r["updated_at"],
            )
        return out

    # ------------------------------------------------------------- per-suite

    def upsert_suite(self, suite: str, status: str) -> None:
        self._ensure_table()
        with self._conn_factory() as conn:
            conn.execute(
                """
                INSERT INTO self_test_suite_status (suite, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(suite) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (suite, status, self._now_iso()),
            )
            conn.commit()

    def get_suite_statuses(self) -> Dict[str, str]:
        self._ensure_table()
        with self._conn_factory() as conn:
            rows = conn.execute(
                "SELECT suite, status FROM self_test_suite_status"
            ).fetchall()
        return {r["suite"]: r["status"] for r in rows}

    # ------------------------------------------------------------- reset

    def clear_all(self) -> None:
        self._ensure_table()
        with self._conn_factory() as conn:
            conn.execute("DELETE FROM self_test_status")
            conn.execute("DELETE FROM self_test_suite_status")
            conn.commit()

    # ------------------------------------------------------------- meta

    def get_build_stamp(self) -> Optional[str]:
        self._ensure_table()
        with self._conn_factory() as conn:
            row = conn.execute(
                "SELECT value FROM self_test_meta WHERE key = 'build_stamp'"
            ).fetchone()
        return row["value"] if row else None

    def set_build_stamp(self, stamp: str) -> None:
        self._ensure_table()
        with self._conn_factory() as conn:
            conn.execute(
                """
                INSERT INTO self_test_meta (key, value, updated_at)
                VALUES ('build_stamp', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (stamp, self._now_iso()),
            )
            conn.commit()