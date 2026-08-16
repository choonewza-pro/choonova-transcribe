"""
Unit tests for the self-test build fingerprint / reset-on-new-build logic.
"""

import os
import shutil
import tempfile
import unittest

from app.modules.apitest.application.build_stamp import (
    compute_build_fingerprint,
    reset_self_test_status_on_new_build,
)
from app.modules.apitest.domain.ports import SelfTestStatusRepository


class FakeStatusRepo(SelfTestStatusRepository):
    def __init__(self):
        self.tests = {}
        self.suites = {}
        self.stamp = None
        self.clear_calls = 0

    def upsert_test(self, suite, test_order, test_label, status):
        self.tests[(suite, test_order)] = status

    def get_tests(self, suite):
        return {}

    def upsert_suite(self, suite, status):
        self.suites[suite] = status

    def get_suite_statuses(self):
        return dict(self.suites)

    def clear_all(self):
        self.clear_calls += 1
        self.tests.clear()
        self.suites.clear()

    def get_build_stamp(self):
        return self.stamp

    def set_build_stamp(self, stamp):
        self.stamp = stamp


class BuildStampTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.src = os.path.join(self._tmp, "app")
        os.makedirs(self.src)
        self._write("a.py", "print('hello')\n")
        self._write("b.py", "x = 1\n")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, name, content):
        with open(os.path.join(self.src, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_fingerprint_stable_for_same_files(self):
        h1 = compute_build_fingerprint(self.src)
        h2 = compute_build_fingerprint(self.src)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_fingerprint_changes_when_content_changes(self):
        h1 = compute_build_fingerprint(self.src)
        self._write("a.py", "print('world')\n")
        h2 = compute_build_fingerprint(self.src)
        self.assertNotEqual(h1, h2)

    def test_fingerprint_ignores_pycache(self):
        cache = os.path.join(self.src, "__pycache__")
        os.makedirs(cache)
        with open(os.path.join(cache, "a.cpython-312.pyc"), "wb") as f:
            f.write(b"\x00\x01")
        h1 = compute_build_fingerprint(self.src)
        with open(os.path.join(cache, "a.cpython-312.pyc"), "wb") as f:
            f.write(b"\xff\xff")
        h2 = compute_build_fingerprint(self.src)
        self.assertEqual(h1, h2)

    def test_reset_on_first_boot(self):
        repo = FakeStatusRepo()
        self.assertTrue(reset_self_test_status_on_new_build(repo, "fp1"))
        self.assertEqual(repo.stamp, "fp1")
        self.assertEqual(repo.clear_calls, 1)

    def test_no_reset_on_same_build(self):
        repo = FakeStatusRepo()
        reset_self_test_status_on_new_build(repo, "fp1")
        self.assertFalse(reset_self_test_status_on_new_build(repo, "fp1"))
        self.assertEqual(repo.clear_calls, 1)

    def test_reset_when_build_changed(self):
        repo = FakeStatusRepo()
        reset_self_test_status_on_new_build(repo, "fp1")
        self.assertTrue(reset_self_test_status_on_new_build(repo, "fp2"))
        self.assertEqual(repo.stamp, "fp2")
        self.assertEqual(repo.clear_calls, 2)


if __name__ == "__main__":
    unittest.main()