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
from app.modules.apitest.domain.ports import ApiHttpPort


class FakeApiHttp(ApiHttpPort):
    """Dict-backed stub implementing ApiHttpPort for the runner."""

    def __init__(self):
        self.responses = {}
        self.poll_sequences = {}
        self.post_sequences = {}
        self.calls = []

    def set(self, method, path, status, body):
        self.responses[(method, path)] = (status, body)

    def set_poll(self, path, interim_bodies, terminal_body):
        self.poll_sequences[path] = list(interim_bodies) + [terminal_body]

    def set_post_seq(self, path, bodies):
        self.post_sequences[path] = list(bodies)

    async def post_multipart(self, path, files=None, data=None, headers=None, timeout=60.0):
        self.calls.append(("POST", path))
        seq = self.post_sequences.get(path)
        if seq:
            return (202, seq.pop(0))
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


def _find_test(report, path):
    return next((t for t in report.tests if t.path == path), None)


class ApiTestRunnerTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        with open(os.path.join(self._tmp, "test-audio-th.wav"), "wb") as f:
            f.write(b"\x00" * 256)
        with open(os.path.join(self._tmp, "The-Frog-and-The-Ox.mp4"), "wb") as f:
            f.write(b"\x00" * 512)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _runner(self, fake, **kw):
        return ApiTestRunner(
            http=fake,
            assets_dir=self._tmp,
            max_transcribe_wait=5,
            max_compress_wait=5,
            poll_interval=0.0,
            **kw,
        )

    def _configure_all_good(self, fake):
        fake.set("GET", "/healthz", 200, {
            "status": "ok", "service": "typhoon-asr-service", "device": "cuda",
            "execution_device": "GPU", "model_load_mode": "always",
            "model_idle_timeout_sec": 900.0, "typhoon_model_state": "loaded",
            "whisper_model_state": "idle",
        })
        fake.set("POST", "/v1/audio/transcribe", 200, {
            "status": "success", "text": "สวัสดีครับ",
            "duration_seconds": 3.42, "elapsed_seconds": 0.08, "rtf": 0.02,
            "timestamps": [{"word": "สวัสดีครับ", "start": 0.0, "end": 3.42}],
        })

        # ------- transcribe family
        fake.set("POST", "/v1/media/transcribe/jobs", 202, {
            "status": "accepted", "id": "t1", "filename": "The-Frog-and-The-Ox.mp4",
            "language": "th", "message": "Job created",
        })
        fake.set("GET", "/v1/media/transcribe/jobs?limit=5&include_text=false", 200, [
            {"id": "t1", "filename": "The-Frog-and-The-Ox.mp4", "status": "completed",
             "progress": 100.0, "stage": "completed", "created_at": "2026-01-01T00:00:00Z"},
        ])
        transcribe_done = {
            "id": "t1", "type": "transcription", "filename": "The-Frog-and-The-Ox.mp4",
            "file_size_bytes": 14383029, "language": "th", "model": "typhoon-asr-realtime",
            "status": "completed", "stage": "completed", "progress": 100.0,
            "total_chunks": 2, "completed_chunks": 2, "duration": 45.5, "processing_time": 10.0,
            "target_chunk_sec": 45.0, "max_chunk_sec": 90.0,
            "result": {"text": "กบกับวัว", "segments": [{"text": "กบกับวัว", "start": 0.0, "end": 45.5}]},
            "error": None, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z",
            "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:01Z",
        }
        fake.set_poll("/v1/media/transcribe/jobs/t1",
                      [{"status": "processing", "stage": "transcribing", "progress": 50.0}],
                      transcribe_done)
        fake.set("GET", "/v1/media/transcribe/jobs/t1/export/txt", 200, "กบกับวัว\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t1/export/srt", 200, "1\n00:00:00,000 --> 00:00:45,500\nกบกับวัว\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t1/export/json", 200, {
            "id": "t1", "filename": "The-Frog-and-The-Ox.mp4", "duration": 45.5, "text": "กบกับวัว",
        })
        fake.set("DELETE", "/v1/media/transcribe/jobs/t1", 200, {"status": "success", "message": "deleted"})

        # ------- compress family
        fake.set("POST", "/v1/media/compress/jobs", 202, {
            "status": "accepted", "job_id": "c1", "filename": "The-Frog-and-The-Ox.mp4",
            "queue_position": 1, "queue_length": 0, "message": "Job created",
        })
        fake.set("GET", "/v1/media/compress/jobs?limit=5", 200, [
            {"job_id": "c1", "filename": "The-Frog-and-The-Ox.mp4", "status": "completed",
             "progress_pct": 100.0, "current_stage": "completed", "created_at": "2026-01-01T00:00:00Z"},
        ])
        fake.set("GET", "/v1/media/compress/retention", 200, {
            "retention_hours": 24.0, "last_cleanup_at": None, "last_cleanup_count": 0,
        })
        compress_done = {
            "job_id": "c1", "filename": "The-Frog-and-The-Ox.mp4", "file_size_bytes": 14383029,
            "status": "completed", "progress_pct": 100.0, "current_stage": "completed",
            "target_width": 0, "bitrate_kbps": 0, "crf": 28, "preset": "medium",
            "encoder": "libx264", "trim_start": 0.0, "trim_end": 0.0,
            "audio_extract_format": "", "input_width": 1280, "input_height": 720,
            "duration_seconds": 45.5, "output_path": "/tmp/choonova-transcribe-jobs/c1/output.mp4",
            "output_size_bytes": 8000000, "output_width": 1280, "output_height": 720,
            "elapsed_seconds": 30.0, "queue_position": 0, "queue_length": 0,
            "audio_extract_path": None, "audio_extract_size_bytes": 0, "audio_exists": False,
            "error_message": None, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z",
        }
        fake.set_poll("/v1/media/compress/jobs/c1",
                      [{"status": "queued", "current_stage": "queued", "progress_pct": 0.0}],
                      compress_done)
        fake.set("DELETE", "/v1/media/compress/jobs/c1", 200, {"status": "success", "message": "deleted"})

    # ------------------------------------------------------------------ tests

    def test_full_suite_passes_and_cleans_up(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        runner = self._runner(fake)
        report = asyncio.run(runner.run(cleanup=True))

        self.assertEqual(report.total, 14)
        self.assertEqual(report.passed_count, 14)
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(report.overall_passed)
        # Cleanup DELETE must have hit both created jobs
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/t1"), fake.calls)
        self.assertIn(("DELETE", "/v1/media/compress/jobs/c1"), fake.calls)

    def test_missing_field_is_reported_as_failure(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        body = dict(fake.responses[("POST", "/v1/audio/transcribe")][1])
        body.pop("rtf", None)
        fake.set("POST", "/v1/audio/transcribe", 200, body)

        runner = self._runner(fake)
        report = asyncio.run(runner.run(cleanup=True))

        self.assertFalse(report.overall_passed)
        audio = _find_test(report, "/v1/audio/transcribe")
        self.assertIsNotNone(audio)
        self.assertFalse(audio.passed)
        rtf = next((c for c in audio.field_checks if c.name == "rtf"), None)
        self.assertIsNotNone(rtf)
        self.assertFalse(rtf.present)
        self.assertFalse(rtf.passed)

    def test_failed_job_marks_failure_but_still_cleans_up(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        failed = {
            "id": "t1", "type": "transcription", "filename": "The-Frog-and-The-Ox.mp4",
            "file_size_bytes": 14383029, "language": "th", "model": "typhoon-asr-realtime",
            "status": "failed", "stage": "transcribing", "progress": 40.0,
            "total_chunks": 2, "completed_chunks": 1, "duration": 20.0, "processing_time": 5.0,
            "target_chunk_sec": 45.0, "max_chunk_sec": 90.0, "result": None,
            "error": {"code": "asr_failed", "message": "decode error occurred", "retryable": False},
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z",
            "started_at": "2026-01-01T00:00:00Z", "completed_at": None,
        }
        fake.set_poll("/v1/media/transcribe/jobs/t1", [], failed)

        runner = self._runner(fake)
        report = asyncio.run(runner.run(cleanup=True))

        status_test = _find_test(report, "/v1/media/transcribe/jobs/t1")
        self.assertIsNotNone(status_test)
        self.assertFalse(status_test.passed)
        self.assertIn("decode error occurred", status_test.error_msg)
        # failed job → exports skipped, but cleanup DELETE still runs
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/t1"), fake.calls)
        self.assertNotIn(("GET", "/v1/media/transcribe/jobs/t1/export/txt"), fake.calls)

    def test_poll_timeout_marks_failure_and_still_cleans_up(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        never = [{"status": "processing", "stage": "chunking", "progress": 10.0}]
        fake.set_poll("/v1/media/compress/jobs/c1", never, never[-1])
        runner = ApiTestRunner(
            http=fake, assets_dir=self._tmp,
            max_transcribe_wait=5, max_compress_wait=0.05, poll_interval=0.001,
        )
        report = asyncio.run(runner.run(cleanup=True))

        status_test = _find_test(report, "/v1/media/compress/jobs/c1")
        self.assertIsNotNone(status_test)
        self.assertFalse(status_test.passed)
        self.assertIn("หมดเวลา", status_test.error_msg)
        # timeout → compress job never completed → no output fields, but cleanup still runs
        self.assertIn(("DELETE", "/v1/media/compress/jobs/c1"), fake.calls)

    def test_missing_asset_raises(self):
        os.remove(os.path.join(self._tmp, "The-Frog-and-The-Ox.mp4"))
        fake = FakeApiHttp()
        runner = self._runner(fake)
        with self.assertRaises(AssetNotFoundError):
            asyncio.run(runner.run(cleanup=True))

    def test_cleanup_disabled_skips_delete_tests(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        runner = self._runner(fake)
        report = asyncio.run(runner.run(cleanup=False))

        self.assertEqual(report.total, 12)
        self.assertNotIn(("DELETE", "/v1/media/transcribe/jobs/t1"), fake.calls)
        self.assertNotIn(("DELETE", "/v1/media/compress/jobs/c1"), fake.calls)

    def test_on_start_reports_predicted_total(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        runner = self._runner(fake)
        totals = []

        async def on_start(total):
            totals.append(total)

        asyncio.run(runner.run(cleanup=True, on_start=on_start))
        self.assertEqual(totals, [14])
        totals.clear()
        asyncio.run(runner.run(cleanup=False, on_start=on_start))
        self.assertEqual(totals, [12])

    def test_pyannote_suite_passes_and_cleans_up(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        # Configure pyannote specific mock responses
        fake.set("POST", "/v1/audio/transcribe", 200, {
            "status": "success", "text": "[SPEAKER_00]: สวัสดีครับ",
            "duration_seconds": 3.42, "elapsed_seconds": 0.15, "rtf": 0.04,
            "timestamps": [{"word": "สวัสดีครับ", "start": 0.0, "end": 3.42, "speaker": "SPEAKER_00"}],
        })
        fake.set("POST", "/v1/media/transcribe/jobs", 202, {
            "status": "accepted", "id": "t_py", "filename": "The-Frog-and-The-Ox.mp4",
            "language": "th", "enable_diarization": True, "message": "Job created",
        })
        fake.set_poll("/v1/media/transcribe/jobs/t_py", [], {
            "id": "t_py", "type": "transcription", "filename": "The-Frog-and-The-Ox.mp4",
            "file_size_bytes": 1000, "language": "th", "model": "typhoon-asr-realtime",
            "status": "completed", "stage": "completed", "progress": 100.0,
            "total_chunks": 1, "completed_chunks": 1, "duration": 10.0, "processing_time": 1.0,
            "target_chunk_sec": 45.0, "max_chunk_sec": 90.0,
            "result": {"text": "[SPEAKER_00]: สวัสดีครับ", "srt": "1\n00:00:00,000 --> 00:00:10,000\n[SPEAKER_00]: สวัสดีครับ\n"},
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z",
            "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:01Z",
        })
        fake.set("GET", "/v1/media/transcribe/jobs/t_py/export/txt", 200, "[SPEAKER_00]: สวัสดีครับ\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t_py/export/srt", 200, "1\n00:00:00,000 --> 00:00:10,000\n[SPEAKER_00]: สวัสดีครับ\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t_py/export/json", 200, {
            "id": "t_py", "filename": "The-Frog-and-The-Ox.mp4", "duration": 10.0, "text": "[SPEAKER_00]: สวัสดีครับ",
        })
        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="pyannote", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 9)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/t_py"), fake.calls)

    def test_whisperx_suite_passes_and_cleans_up(self):
        fake = FakeApiHttp()
        self._configure_all_good(fake)
        # Configure whisperx specific mock responses
        fake.set("POST", "/v1/audio/transcribe", 200, {
            "status": "success", "text": "Hello world",
            "duration_seconds": 2.5, "elapsed_seconds": 0.2, "rtf": 0.08,
            "timestamps": [{"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}],
        })
        fake.set("POST", "/v1/media/transcribe/jobs", 202, {
            "status": "accepted", "id": "t_wx", "filename": "The-Frog-and-The-Ox.mp4",
            "language": "auto", "enable_diarization": True, "message": "Job created",
        })
        fake.set_poll("/v1/media/transcribe/jobs/t_wx", [], {
            "id": "t_wx", "type": "transcription", "filename": "The-Frog-and-The-Ox.mp4",
            "file_size_bytes": 1000, "language": "auto", "model": "whisperx",
            "status": "completed", "stage": "completed", "progress": 100.0,
            "total_chunks": 1, "completed_chunks": 1, "duration": 10.0, "processing_time": 1.5,
            "target_chunk_sec": 25.0, "max_chunk_sec": 30.0,
            "result": {"text": "Hello world", "srt": "1\n00:00:00,000 --> 00:00:02,500\nHello world\n"},
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z",
            "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:01Z",
        })
        fake.set("GET", "/v1/media/transcribe/jobs/t_wx/export/txt", 200, "Hello world\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t_wx/export/srt", 200, "1\n00:00:00,000 --> 00:00:02,500\nHello world\n")
        fake.set("GET", "/v1/media/transcribe/jobs/t_wx/export/json", 200, {
            "id": "t_wx", "filename": "The-Frog-and-The-Ox.mp4", "duration": 10.0, "text": "Hello world",
        })
        runner = self._runner(fake)
        report = asyncio.run(runner.run(suite="whisperx", cleanup=True))
        self.assertTrue(report.overall_passed)
        self.assertEqual(report.total, 9)
        self.assertIn(("DELETE", "/v1/media/transcribe/jobs/t_wx"), fake.calls)

    def test_asset_info_reports_availability(self):
        fake = FakeApiHttp()
        runner = self._runner(fake)
        info = runner.asset_info()
        assets = info["assets"]
        self.assertTrue(assets["test-audio-th.wav"]["exists"])
        self.assertTrue(assets["The-Frog-and-The-Ox.mp4"]["exists"])
        self.assertEqual(assets["test-audio-th.wav"]["size_bytes"], 256)

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
            "result": {"text": "สวัสดีครับ", "segments": segments},
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
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            {"speaker": "SPEAKER_01", "start": 3.0, "end": 6.0, "word": "ครับ", "text": "ครับ"},
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
            {"start": 0.0, "end": 1.0, "word": "สวัสดี", "text": "สวัสดี"},
            {"start": 1.0, "end": 2.0, "word": "ครับ", "text": "ครับ"},
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
        # word-diar expects speaker labels; diarized job without speaker → fail
        segments = [
            {"start": 0.0, "end": 3.0, "word": "สวัสดี", "text": "สวัสดี"},
            {"start": 3.0, "end": 6.0, "word": "ครับ", "text": "ครับ"},
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
        # whisper model unexpectedly returns word-level segments → should fail
        segments = [{"start": 0.0, "end": 1.0, "word": "สวัสดี", "text": "สวัสดี"}]
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


if __name__ == "__main__":
    unittest.main()