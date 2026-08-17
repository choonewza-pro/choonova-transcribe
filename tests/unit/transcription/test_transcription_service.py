import unittest
import os
import tempfile
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
from app.modules.transcription.domain.entities import TranscriptionJob, TranscriptionRequest
from app.modules.transcription.domain.ports import JobRepositoryPort, MediaProcessorPort
from app.modules.transcription.application.transcription_service import TranscriptionService
from app.core.exceptions import ValidationException, StorageException, QueueFullException


class FakeJobRepository(JobRepositoryPort):
    """In-memory fake repository for unit tests. No DB, no I/O."""

    def __init__(self):
        self.jobs: Dict[str, TranscriptionJob] = {}

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        return self.jobs.get(job_id)

    def update_progress(
        self, job_id: str, progress_pct: float, current_stage: str,
        completed_chunks: int, elapsed_seconds: float,
    ) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].progress = progress_pct
            self.jobs[job_id].stage = current_stage
            self.jobs[job_id].completed_chunks = completed_chunks

    def complete_job(
        self, job_id: str, result_text: str, timestamps_json: str,
        srt_text: str, elapsed_seconds: float,
    ) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "completed"
            self.jobs[job_id].result = {"text": result_text, "srt": srt_text}
            self.jobs[job_id].processing_time = elapsed_seconds

    def fail_job(self, job_id: str, error_message: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "failed"
            self.jobs[job_id].error = {"message": error_message}

    def update_status(
        self, job_id: str, status: str,
        progress: Optional[float] = None,
        stage: Optional[str] = None,
        completed_chunks: Optional[int] = None,
        total_chunks: Optional[int] = None,
        duration: Optional[float] = None,
        processing_time: Optional[float] = None,
        result_json: Optional[str] = None,
        error_json: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = status
            if progress is not None:
                self.jobs[job_id].progress = progress
            if stage is not None:
                self.jobs[job_id].stage = stage

    def list_jobs(
        self, limit: int = 50, offset: int = 0,
        status_filter: Optional[str] = None,
    ) -> List[TranscriptionJob]:
        jobs = list(self.jobs.values())
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        return jobs[offset:offset + limit]

    def delete_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        queued = [j for j in self.jobs.values() if j.status == "queued"]
        return {"queue_position": 1, "queue_length": len(queued)}

    def count_queued(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "queued")

    def get_retention_summary(self) -> Dict[str, Any]:
        return {"retention_hours": 24}


class FakeMediaProcessor(MediaProcessorPort):
    """In-memory fake media processor so tests control disk-space responses without touching the filesystem."""

    def __init__(self, disk_ok: bool = True):
        self.disk_ok = disk_ok

    def extract_and_chunk_audio(self, media_path: str, target_chunk_sec: float = 30.0) -> List[Any]:
        return []

    def check_disk_space(self, path: str, required_gb: float = 5.0) -> bool:
        return self.disk_ok

    def safe_delete_dir(self, dir_path: str) -> bool:
        return True

    def get_duration(self, media_path: str) -> float:
        return 0.0


class TestTranscriptionService(unittest.TestCase):

    def test_create_and_get_transcription_job(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)

        created = service.create_job(filename="audio.wav", file_size_bytes=500, language="th")
        self.assertIsNotNone(created.id)
        self.assertEqual(created.status, "queued")
        self.assertEqual(created.language, "th")

        fetched = service.get_job(created.id)
        self.assertEqual(fetched.filename, "audio.wav")

    def test_get_job_or_none_returns_none_when_missing(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        result = service.get_job_or_none("nonexistent-id")
        self.assertIsNone(result)

    def test_list_jobs_returns_all(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        service.create_job(filename="b.wav", file_size_bytes=200, language="en")
        jobs = service.list_jobs()
        self.assertEqual(len(jobs), 2)

    def test_list_jobs_with_status_filter(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        repo.update_status(job.id, status="completed")
        service.create_job(filename="b.wav", file_size_bytes=200, language="en")

        queued = service.list_jobs(status_filter="queued")
        self.assertEqual(len(queued), 1)
        completed = service.list_jobs(status_filter="completed")
        self.assertEqual(len(completed), 1)

    def test_delete_job(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        self.assertTrue(service.delete_job(job.id))
        self.assertIsNone(service.get_job_or_none(job.id))

    def test_update_status(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        service.update_status(job_id=job.id, status="cancelled")
        updated = service.get_job_or_none(job.id)
        self.assertEqual(updated.status, "cancelled")

    def test_count_queued(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        service.create_job(filename="b.wav", file_size_bytes=200, language="th")
        self.assertEqual(service.count_queued(), 2)

    def test_create_job_with_diarization(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(
            filename="interview.mp4",
            file_size_bytes=5000000,
            language="th",
            enable_diarization=True,
        )
        self.assertTrue(job.enable_diarization)
        retrieved = service.get_job_or_none(job.id)
        self.assertIsNotNone(retrieved)
        self.assertTrue(retrieved.enable_diarization)

    def test_create_job_with_speaker_counts(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(
            filename="podcast.mp4",
            file_size_bytes=10000000,
            language="en",
            enable_diarization=True,
            num_speakers=2,
            min_speakers=2,
            max_speakers=2,
        )
        self.assertTrue(job.enable_diarization)
        self.assertEqual(job.num_speakers, 2)
        self.assertEqual(job.min_speakers, 2)
        self.assertEqual(job.max_speakers, 2)
        retrieved = service.get_job_or_none(job.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.num_speakers, 2)

    def test_job_to_dict_includes_speakers(self):
        from app.api.v1.transcription_router import _job_to_dict
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        job = service.create_job(
            filename="meeting.mp4",
            file_size_bytes=2000000,
            language="th",
            enable_diarization=True,
            num_speakers=3,
            min_speakers=2,
            max_speakers=4,
        )
        d = _job_to_dict(job)
        self.assertEqual(d["num_speakers"], 3)
        self.assertEqual(d["min_speakers"], 2)
        self.assertEqual(d["max_speakers"], 4)
        self.assertTrue(d["enable_diarization"])

    # ------------------------------------------------------------------
    # prepare_request — shared request-preparation use case (audio endpoints)
    # ------------------------------------------------------------------

    def test_prepare_request_default_th_transcribe(self):
        req = TranscriptionService.prepare_request(
            language="th", model="thai-whisper"
        )
        self.assertIsInstance(req, TranscriptionRequest)
        self.assertEqual(req.language, "th")
        self.assertEqual(req.model, "thai-whisper")
        self.assertFalse(req.enable_diarization)
        self.assertFalse(req.with_timestamps)

    def test_prepare_request_invalid_language_raises(self):
        with self.assertRaises(ValidationException) as ctx:
            TranscriptionService.prepare_request(
                language="xx", model="whisper"
            )
        self.assertIn("Unsupported language", ctx.exception.message)

    def test_prepare_request_invalid_speaker_counts(self):
        cases = [
            ({"num_speakers": 0}, "num_speakers must be greater than 0."),
            ({"min_speakers": 0}, "min_speakers must be greater than 0."),
            ({"max_speakers": 0}, "max_speakers must be greater than 0."),
            ({"min_speakers": 3, "max_speakers": 2}, "min_speakers cannot exceed max_speakers."),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationException) as ctx:
                    TranscriptionService.prepare_request(
                        language="th", model="thai-whisper", **kwargs
                    )
                self.assertEqual(ctx.exception.message, message)

    def test_prepare_request_typhoon_with_timestamps_raises(self):
        with self.assertRaises(ValidationException) as ctx:
            TranscriptionService.prepare_request(
                language="th", model="typhoon", with_timestamps=True
            )
        self.assertEqual(
            ctx.exception.message,
            "with_timestamps is not supported for model='typhoon'.",
        )

    def test_prepare_request_typhoon_without_timestamps_ok(self):
        req = TranscriptionService.prepare_request(
            language="th", model="typhoon"
        )
        self.assertEqual(req.model, "typhoon")
        self.assertFalse(req.with_timestamps)

    def test_prepare_request_auto_enables_diarization_when_speakers_set(self):
        import app.config as config_module
        original = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = True
        try:
            req = TranscriptionService.prepare_request(
                language="th", model="thai-whisper", num_speakers=2
            )
            self.assertTrue(req.enable_diarization)
            self.assertEqual(req.num_speakers, 2)
        finally:
            config_module.DIARIZATION_ENABLED = original

    def test_prepare_request_rejects_diarization_when_disabled(self):
        import app.config as config_module
        original = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = False
        try:
            with self.assertRaises(ValidationException) as ctx:
                TranscriptionService.prepare_request(
                    language="th", model="thai-whisper",
                    enable_diarization=True,
                )
            self.assertIn("disabled", ctx.exception.message)
        finally:
            config_module.DIARIZATION_ENABLED = original

    def test_prepare_request_rejects_diarization_when_auto_enabled_but_switch_off(self):
        import app.config as config_module
        original = config_module.DIARIZATION_ENABLED
        config_module.DIARIZATION_ENABLED = False
        try:
            with self.assertRaises(ValidationException) as ctx:
                TranscriptionService.prepare_request(
                    language="th", model="thai-whisper", num_speakers=2
                )
            self.assertIn("disabled", ctx.exception.message)
        finally:
            config_module.DIARIZATION_ENABLED = original

    def test_prepare_request_rejects_model_not_in_matrix(self):
        with self.assertRaises(ValidationException) as ctx:
            TranscriptionService.prepare_request(
                language="th", model="whisperx"
            )
        self.assertIn("not supported", ctx.exception.message)

    def test_prepare_request_whisperx_requires_hf_token(self):
        import app.config as config_module
        original_token = config_module.HF_TOKEN
        original_diar = config_module.DIARIZATION_ENABLED
        config_module.HF_TOKEN = ""
        config_module.DIARIZATION_ENABLED = True
        try:
            with self.assertRaises(ValidationException) as ctx:
                TranscriptionService.prepare_request(
                    language="th", model="whisperx",
                    enable_diarization=True,
                )
            self.assertIn("HF_TOKEN", ctx.exception.message)
        finally:
            config_module.HF_TOKEN = original_token
            config_module.DIARIZATION_ENABLED = original_diar

    # ------------------------------------------------------------------
    # ensure_capacity — queue/disk guards before persisting uploads
    # ------------------------------------------------------------------

    def test_ensure_capacity_raises_when_queue_full(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        service.create_job(filename="a.wav", file_size_bytes=100, language="th")
        service.create_job(filename="b.wav", file_size_bytes=100, language="th")
        with self.assertRaises(QueueFullException) as ctx:
            service.ensure_capacity("/tmp", 5.0, max_queued=2)
        self.assertIn("queue is full", ctx.exception.message)

    def test_ensure_capacity_raises_when_disk_full(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo, media_processor=FakeMediaProcessor(disk_ok=False))
        with self.assertRaises(StorageException) as ctx:
            service.ensure_capacity("/tmp", 5.0, max_queued=10)
        self.assertIn("Insufficient disk space", ctx.exception.message)

    def test_ensure_capacity_passes_with_headroom(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo, media_processor=FakeMediaProcessor(disk_ok=True))
        service.ensure_capacity("/tmp", 5.0, max_queued=10)

    # ------------------------------------------------------------------
    # _validate_saved_file — 3-layer file security (magic bytes + ffprobe)
    # ------------------------------------------------------------------

    def test_validate_saved_file_rejects_non_media_file(self):
        from app.api.v1.transcription_router import _validate_saved_file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"this is definitely not a media file")
            path = tmp.name
        try:
            with self.assertRaises(HTTPException) as ctx:
                _validate_saved_file(path, max_duration_sec=3600.0)
            self.assertEqual(ctx.exception.status_code, 422)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

