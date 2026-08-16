"""
Unit tests for the in-memory self-test run registry.

Follows the repo convention: stdlib unittest, no mocking library, simple
Arrange-Act-Assert with constructor injection of the registry.
"""

import unittest

from app.modules.apitest.application.run_registry import RunRegistry


class RunRegistryTest(unittest.TestCase):

    def setUp(self):
        self.reg = RunRegistry(max_runs=3)

    def test_start_creates_active_run(self):
        state = self.reg.start("r1", "word-diar", cleanup=True)
        self.assertEqual(state.status, "running")
        self.assertIsNotNone(state.started_at)
        self.assertEqual(self.reg.active_run().run_id, "r1")

    def test_active_run_none_when_idle(self):
        self.assertIsNone(self.reg.active_run())

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.reg.get("nope"))

    def test_record_test_and_progress(self):
        self.reg.start("r1", "word-diar")
        self.reg.set_expected_total("r1", 6)
        self.reg.record_test("r1", {"order": 1, "path": "/x", "passed": True})
        self.reg.record_progress("r1", {"path": "/x", "status": "processing", "progress": 50})
        state = self.reg.get("r1")
        self.assertEqual(state.expected_total, 6)
        self.assertEqual(len(state.tests), 1)
        self.assertEqual(state.latest_progress["progress"], 50)
        self.assertEqual(state.to_dict()["status"], "running")

    def test_finish_clears_active_and_sets_summary(self):
        self.reg.start("r1", "word-diar")
        summary = {"total": 6, "passed_count": 6, "failed_count": 0, "overall_passed": True}
        self.reg.finish("r1", summary=summary)
        self.assertIsNone(self.reg.active_run())
        state = self.reg.get("r1")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.summary["total"], 6)
        self.assertIsNotNone(state.finished_at)
        self.assertIsNone(state.error)

    def test_finish_failed_sets_error(self):
        self.reg.start("r1", "word-diar")
        self.reg.finish("r1", error="boom")
        state = self.reg.get("r1")
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.error, "boom")

    def test_list_newest_first_and_capped(self):
        for i in range(5):
            self.reg.start(f"r{i}", "word-only")
            self.reg.finish(f"r{i}", summary={})
        items = self.reg.list()
        self.assertEqual(len(items), 3)  # capped at max_runs=3
        self.assertEqual(items[0].run_id, "r4")
        self.assertEqual(items[-1].run_id, "r2")

    def test_evict_never_removes_active(self):
        for i in range(5):
            self.reg.start(f"r{i}", "word-only")
            self.reg.finish(f"r{i}", summary={})
        self.reg.start("active1", "word-diar")
        self.assertIsNotNone(self.reg.active_run())
        self.assertEqual(self.reg.active_run().run_id, "active1")
        self.assertIn("active1", self.reg.get("active1").run_id)


if __name__ == "__main__":
    unittest.main()