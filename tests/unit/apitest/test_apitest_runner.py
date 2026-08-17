"""
Unit tests for ApiTestRunner using an in-memory FakeApiHttp.

Follows the repo convention: stdlib unittest, no mocking library, simple
Arrange-Act-Assert with constructor injection of a fake port. The fake
records calls (so we can assert cleanup DELETE ran) and simulates job
polling via scripted status sequences.
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from app.modules.apitest.application.apitest_runner import (
    ApiTestRunner,
    AssetNotFoundError,
)
from app.modules.apitest.application.run_registry import RunRegistry
from app.modules.apitest.domain.ports import ApiHttpPort


class FakeApiHttp(ApiHttpPort):
    """Dict-backed stub implementing ApiHttpPort for the runner."""

    def __init__(self):
        self.responses = {}
        self.poll_sequences = {}
        self.post_sequences = {}
        self.post_seq_status = {}
        self.calls = []

    def set(self, method, path, status, body):
        self.responses[(method, path)] = (status, body)

    def set_poll(self, path, interim_bodies, terminal_body):
        self.poll_sequences[path] = list(interim_bodies) + [terminal_body]

    def set_post_seq(self, path, bodies, status=202):
        self.post_sequences[path] = list(bodies)
        self.post_seq_status[path] = status

    async def post_multipart(self, path, files=None, data=None, headers=None, timeout=60.0):
        self.calls.append(("POST", path))
        seq = self.post_sequences.get(path)
        if seq:
            return (self.post_seq_status.get(path, 202), seq.pop(0))
        return self.responses.get(("POST", path), (200, {}))

    async def get(self, path, headers=None, timeout=60.0):
        self.calls.append(("GET", path))
        seq = self.poll_sequences.get(path)
        if seq:
            return (200, seq.pop(0))
        return self.responses.get(("GET", path), (200, {}))

    async def delete(self, path, headers=None, timeout=60.0):
        self.calls.append(("DELETE", path))
        return self.responses.get(("DELETE", path), (200, {"status": "success", "message": "ok"}))


class ApiTestRunnerTest(unittest.TestCase):

    def setUp(self):
        import app.config as config_module
        self._original_diar = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = True
        self._tmp = tempfile.mkdtemp()
        with open(os.path.join(self._tmp, "test-audio-th.wav"), "wb") as f:
            f.write(b"\x00" * 256)

    def tearDown(self):
        import app.config as config_module
        config_module.DIARIZATION_ENABLED = self._original_diar
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _runner(self, fake, **kw):
        return ApiTestRunner(
            http=fake,
            assets_dir=self._tmp,
            max_transcribe_wait=5,
            poll_interval=0.0,
            **kw,
        )

    # -------------------------------------------------------- audio word-level suites

    @staticmethod
    def _audio_create_body(job_id, model, lang, enable_diar):
        return {
            "status": "accepted", "id": job_id, "filename": "test-audio-th.wav",
            "language": lang, "model": model, "enable_diarization": enable_diar,
            "message": "Job created",
        }

    @staticmethod
    def _audio_terminal(job_id, model, lang, segments):
        return {
            "id": job_id, "type": "audio", "filename": "test-audio-th.wav",
            "file_size_bytes": 1000, "language": lang, "model": model,
            "status": "completed", "stage": "completed", "progress": 100.0,
            "total_chunks": 1, "completed_chunks": 1, "duration": 8.0,
            "processing_time": 1.0, "target_chunk_sec": 30.0, "max_chunk_sec": 60.0,
            "result": {"text": "à¸ªà¸§à¸±à¸ªà¸”à¸µà¸„à¸£à¸±à¸š", "segments": segments},
            "error": None, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:01Z", "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:01Z",
        }

    def _configure_audio_word_suite(self, fake, creates, terminals, model_ids):
        """Wire create responses + per-job poll terminals + DELETE cleanup."""
        fake.set_post_seq("/v1/audio/transcribe/jobs", creates)
        for job_id, terminal in zip(model_ids, terminals):
            fake.set_poll(f"/v1/media/transcribe/jobs/{job_id}", [], terminal)
            fake.set("DELETE", f"/v1/media/transcribe/jobs/{job_id}", 200,
                     {"status": "success", "message": "deleted"})

    def test_word_diar_suite_passes_and_cleans_up(self):
        fake = FakeApiHttp()
        segments = [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
            {"speaker": "SPEAKER_01", "start": 3.0, "end": 6.0, "word": "à¸„à¸£à¸±à¸š", "text": "à¸„à¸£à¸±à¸š"},
        ]
        creates = [
            self._audio_create_body("wa1", "thai-whisper", "th", True),
            self._audio_create_body("wa2", "whisperx", "auto", True),
        ]
        terminals = [
            self._audio_terminal("wa1", "thai-whisper", "th", segments),
            self._audio_terminal("wa2", "whisperx", "auto", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["wa1", "wa2"])

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="word-diar", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 6)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wa1"), fake.calls)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wa2"), fake.calls)

    def test_word_only_suite_passes_and_cleans_up(self):
        fake = FakeApiHttp()
        segments = [
            {"start": 0.0, "end": 1.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
            {"start": 1.0, "end": 2.0, "word": "à¸„à¸£à¸±à¸š", "text": "à¸„à¸£à¸±à¸š"},
        ]
        creates = [
            self._audio_create_body("wo1", "thai-whisper", "th", False),
            self._audio_create_body("wo2", "whisper", "th", False),
        ]
        terminals = [
            self._audio_terminal("wo1", "thai-whisper", "th", segments),
            self._audio_terminal("wo2", "whisper", "th", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["wo1", "wo2"])

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="word-only", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 6)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wo1"), fake.calls)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wo2"), fake.calls)

    def test_no_word_suite_passes_when_segments_empty(self):
        fake = FakeApiHttp()
        creates = [
            self._audio_create_body("nw1", "typhoon", "th", False),
            self._audio_create_body("nw2", "thai-whisper", "th", False),
            self._audio_create_body("nw3", "whisper", "th", False),
        ]
        terminals = [
            self._audio_terminal("nw1", "typhoon", "th", []),
            self._audio_terminal("nw2", "thai-whisper", "th", []),
            self._audio_terminal("nw3", "whisper", "th", []),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["nw1", "nw2", "nw3"])

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="no-word", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 9)
        for jid in ("nw1", "nw2", "nw3"):
            self.assertIn(("DELETE", f"/v1/media/transcribe/jobs/{jid}"), fake.calls)

    def test_word_diar_suite_fails_when_speaker_missing(self):
        fake = FakeApiHttp()
        # word-diar expects speaker labels; diarized job without speaker â†’ fail
        segments = [
            {"start": 0.0, "end": 3.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
            {"start": 3.0, "end": 6.0, "word": "à¸„à¸£à¸±à¸š", "text": "à¸„à¸£à¸±à¸š"},
        ]
        creates = [
            self._audio_create_body("wf1", "thai-whisper", "th", True),
            self._audio_create_body("wf2", "whisperx", "auto", True),
        ]
        terminals = [
            self._audio_terminal("wf1", "thai-whisper", "th", segments),
            self._audio_terminal("wf2", "whisperx", "auto", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["wf1", "wf2"])

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="word-diar", cleanup=True))
        self.assertFalse(report.overall_passed)
        self.assertEqual(report.passed_count, 4)
        self.assertEqual(report.failed_count, 2)
        # cleanup still runs for both jobs
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wf1"), fake.calls)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/wf2"), fake.calls)

    def test_no_word_suite_fails_when_words_present(self):
        fake = FakeApiHttp()
        # whisper model unexpectedly returns word-level segments â†’ should fail
        segments = [{"start": 0.0, "end": 1.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"}]
        creates = [
            self._audio_create_body("nf1", "typhoon", "th", False),
            self._audio_create_body("nf2", "thai-whisper", "th", False),
            self._audio_create_body("nf3", "whisper", "th", False),
        ]
        terminals = [
            self._audio_terminal("nf1", "typhoon", "th", []),
            self._audio_terminal("nf2", "thai-whisper", "th", []),
            self._audio_terminal("nf3", "whisper", "th", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["nf1", "nf2", "nf3"])

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="no-word", cleanup=True))
        self.assertFalse(report.overall_passed)
        self.assertEqual(report.passed_count, 8)
        self.assertEqual(report.failed_count, 1)

    # -------------------------------------------------------- sync /v1/audio/transcribe suite

    @staticmethod
    def _sync_body(model, segments):
        return {
            "status": "success",
            "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µà¸„à¸£à¸±à¸š",
            "duration_seconds": 8.0,
            "elapsed_seconds": 1.2,
            "rtf": 0.15,
            "segments": segments,
            "model": model,
        }

    def test_sync_suite_passes_with_segments(self):
        fake = FakeApiHttp()
        # POST /v1/audio/transcribe responses, in the runner's model order:
        # thai-whisper+diar (word+speaker), thai-whisper (word), whisper (word), typhoon (no word)
        fake.set_post_seq("/v1/audio/transcribe", [
            self._sync_body("thai-whisper", [
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
                {"speaker": "SPEAKER_01", "start": 3.0, "end": 6.0, "word": "ครับ", "text": "ครับ"},
            ]),
            self._sync_body("thai-whisper", [
                {"start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            ]),
            self._sync_body("whisper", [
                {"start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            ]),
            self._sync_body("typhoon", None),
        ], status=200)

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="sync", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 4)
        self.assertEqual(report.passed_count, 4)

    def test_sync_suite_fails_when_word_data_missing(self):
        fake = FakeApiHttp()
        # thai-whisper+diar returns segments WITHOUT word/text â†’ the
        # expect_words checks must fail (segments field carries no word data).
        fake.set_post_seq("/v1/audio/transcribe", [
            self._sync_body("thai-whisper", [
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0},
            ]),
            self._sync_body("thai-whisper", [
                {"start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            ]),
            self._sync_body("whisper", [
                {"start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            ]),
            self._sync_body("typhoon", None),
        ], status=200)

        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="sync", cleanup=True))
        self.assertFalse(report.overall_passed)
        self.assertEqual(report.passed_count, 3)
        self.assertEqual(report.failed_count, 1)

    def test_sync_suite_expected_total(self):
        fake = FakeApiHttp()
        fake.set_post_seq("/v1/audio/transcribe", [
            self._sync_body("thai-whisper", [
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            ]),
            self._sync_body("thai-whisper", []),
            self._sync_body("whisper", []),
            self._sync_body("typhoon", None),
        ], status=200)
        runner = self._runner(fake)
        totals = []

        async def on_start(total):
            totals.append(total)

        asyncio.run(runner.run(suite="sync", cleanup=True, on_start=on_start))
        self.assertEqual(totals, [4])

    def test_on_start_reports_predicted_total(self):
        fake = FakeApiHttp()
        segments = [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
        ]
        creates = [
            self._audio_create_body("os1", "thai-whisper", "th", True),
            self._audio_create_body("os2", "whisperx", "auto", True),
        ]
        terminals = [
            self._audio_terminal("os1", "thai-whisper", "th", segments),
            self._audio_terminal("os2", "whisperx", "auto", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["os1", "os2"])
        runner = self._runner(fake)
        totals = []

        async def on_start(total):
            totals.append(total)

        asyncio.run(runner.run(suite="word-diar", cleanup=True, on_start=on_start))
        self.assertEqual(totals, [6])
        totals.clear()
        asyncio.run(runner.run(suite="word-diar", cleanup=False, on_start=on_start))
        self.assertEqual(totals, [4])

    def test_invalid_suite_falls_back_to_word_diar(self):
        fake = FakeApiHttp()
        segments = [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
        ]
        creates = [
            self._audio_create_body("fb1", "thai-whisper", "th", True),
            self._audio_create_body("fb2", "whisperx", "auto", True),
        ]
        terminals = [
            self._audio_terminal("fb1", "thai-whisper", "th", segments),
            self._audio_terminal("fb2", "whisperx", "auto", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["fb1", "fb2"])
        runner = self._runner(fake)
        totals = []

        async def on_start(total):
            totals.append(total)

        # Removed suite keys (e.g. 'typhoon') must fall back to the default word-diar.
        report = asyncio.run(runner.run(suite="typhoon", cleanup=True, on_start=on_start))
        self.assertEqual(totals, [6])
        self.assertEqual(report.total, 6)
        self.assertTrue(report.overall_passed)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/fb1"), fake.calls)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/fb2"), fake.calls)

    def test_run_records_into_registry(self):
        fake = FakeApiHttp()
        segments = [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "à¸ªà¸§à¸±à¸ªà¸”à¸µ", "text": "à¸ªà¸§à¸±à¸ªà¸”à¸µ"},
        ]
        creates = [
            self._audio_create_body("ir1", "thai-whisper", "th", True),
            self._audio_create_body("ir2", "whisperx", "auto", True),
        ]
        terminals = [
            self._audio_terminal("ir1", "thai-whisper", "th", segments),
            self._audio_terminal("ir2", "whisperx", "auto", segments),
        ]
        self._configure_audio_word_suite(fake, creates, terminals, ["ir1", "ir2"])
        runner = self._runner(fake)
        registry = RunRegistry()
        registry.start("run1", "word-diar", cleanup=True)

        async def on_test(t):
            registry.record_test("run1", t.to_dict())

        async def on_progress(p):
            registry.record_progress("run1", p)

        async def on_start(total):
            registry.set_expected_total("run1", total)

        report = asyncio.run(runner.run(
            suite="word-diar", cleanup=True,
            on_test=on_test, on_progress=on_progress, on_start=on_start,
        ))
        registry.finish("run1", summary=report.to_dict())

        state = registry.get("run1")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.expected_total, 6)
        self.assertEqual(len(state.tests), 6)
        self.assertEqual(state.summary["total"], 6)
        self.assertIsNone(registry.active_run())

    def test_missing_asset_raises(self):
        os.remove(os.path.join(self._tmp, "test-audio-th.wav"))
        fake = FakeApiHttp()
        runner = self._runner(fake)
        with self.assertRaises(AssetNotFoundError):
            asyncio.run(runner.run(cleanup=True))

    def test_asset_info_reports_availability(self):
        fake = FakeApiHttp()
        runner = self._runner(fake)
        info = runner.asset_info()
        assets = info["assets"]
        self.assertTrue(assets["test-audio-th.wav"]["exists"])
        self.assertEqual(assets["test-audio-th.wav"]["size_bytes"], 256)
# The video asset is no longer used by any suite.
        self.assertNotIn("The-Frog-and-The-Ox.mp4", assets)

    def test_sync_models_drop_diar_cards_when_disabled(self):
        import app.config as config_module
        original = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = False
        try:
            runner = self._runner(FakeApiHttp())
            models = runner._sync_models()
            self.assertEqual(len(models), 3)
            self.assertTrue(all(not m[3] for m in models))
            self.assertEqual(runner._expected_total(cleanup=True, suite="sync"), 3)
        finally:
            config_module.DIARIZATION_ENABLED = original

    def test_sync_models_keep_diar_cards_when_enabled(self):
        runner = self._runner(FakeApiHttp())
        self.assertEqual(len(runner._sync_models()), 4)

    def test_word_diar_suite_raises_when_diarization_disabled(self):
        import app.config as config_module
        original = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = False
        try:
            runner = self._runner(FakeApiHttp())
            with self.assertRaises(ValueError):
                asyncio.run(runner.run(suite="word-diar", cleanup=True))
        finally:
            config_module.DIARIZATION_ENABLED = original


if __name__ == "__main__":
    unittest.main()
