"""
Unit tests for SQLiteSelfTestStatusRepository using a temp-dir SQLite file.

The repository accepts an injectable connection factory so tests can point it
at a throwaway database instead of the real data/choonova-transcribe.db.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from app.modules.apitest.adapters.outbound.sqlite_self_test_status_repository import (
    SQLiteSelfTestStatusRepository,
)


def _conn_factory(db_path):
    def factory():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    return factory


class SQLiteSelfTestStatusRepositoryTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._db = os.path.join(self._tmp, "test.db")
        self.repo = SQLiteSelfTestStatusRepository(conn_factory=_conn_factory(self._db))

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_upsert_and_get_tests(self):
        self.repo.upsert_test("word-diar", 1, "สร้างงาน (thai-whisper)", "passed")
        self.repo.upsert_test("word-diar", 2, "สถานะงาน (poll)", "failed")
        tests = self.repo.get_tests("word-diar")
        self.assertEqual(len(tests), 2)
        self.assertEqual(tests[1].status, "passed")
        self.assertEqual(tests[1].test_label, "สร้างงาน (thai-whisper)")
        self.assertEqual(tests[2].status, "failed")
        self.assertIsNotNone(tests[1].updated_at)

    def test_upsert_test_overwrites(self):
        self.repo.upsert_test("word-diar", 1, "x", "failed")
        self.repo.upsert_test("word-diar", 1, "x", "passed")
        tests = self.repo.get_tests("word-diar")
        self.assertEqual(tests[1].status, "passed")

    def test_get_tests_empty(self):
        self.assertEqual(self.repo.get_tests("no-word"), {})

    def test_suite_statuses(self):
        self.assertEqual(self.repo.get_suite_statuses(), {})
        self.repo.upsert_suite("word-diar", "passed")
        self.repo.upsert_suite("no-word", "failed")
        self.assertEqual(self.repo.get_suite_statuses(),
                         {"word-diar": "passed", "no-word": "failed"})

    def test_clear_all(self):
        self.repo.upsert_test("word-diar", 1, "x", "passed")
        self.repo.upsert_suite("word-diar", "passed")
        self.repo.clear_all()
        self.assertEqual(self.repo.get_tests("word-diar"), {})
        self.assertEqual(self.repo.get_suite_statuses(), {})

    def test_build_stamp(self):
        self.assertIsNone(self.repo.get_build_stamp())
        self.repo.set_build_stamp("abc123")
        self.assertEqual(self.repo.get_build_stamp(), "abc123")
        self.repo.set_build_stamp("def456")
        self.assertEqual(self.repo.get_build_stamp(), "def456")


if __name__ == "__main__":
    unittest.main()