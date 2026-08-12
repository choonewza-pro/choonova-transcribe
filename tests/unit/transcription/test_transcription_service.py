import unittest
from typing import Optional, List, Dict, Any
from app.modules.transcription.domain.entities import TranscriptionJob
from app.modules.transcription.domain.ports import JobRepositoryPort
from app.modules.transcription.application.transcription_service import TranscriptionService


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

    def test_get_retention_summary(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        summary = service.get_retention_summary()
        self.assertIn("retention_hours", summary)


if __name__ == "__main__":
    unittest.main()
