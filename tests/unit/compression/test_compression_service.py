import unittest
from typing import Optional, List, Dict, Any
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort
from app.modules.compression.application.compression_service import CompressionService


class FakeCompressRepository(CompressionRepositoryPort):
    """In-memory fake repository for unit tests. No DB, no I/O."""

    def __init__(self):
        self.jobs: Dict[str, CompressionJob] = {}

    def create_job(self, job: CompressionJob) -> CompressionJob:
        self.jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[CompressionJob]:
        return self.jobs.get(job_id)

    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].progress_pct = progress_pct
            self.jobs[job_id].current_stage = current_stage
            self.jobs[job_id].elapsed_seconds = elapsed_seconds

    def complete_job(self, job_id: str, output_path: str, output_size_bytes: int, compression_ratio: float, encoder_used: str, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "completed"
            self.jobs[job_id].output_path = output_path
            self.jobs[job_id].output_size_bytes = output_size_bytes
            self.jobs[job_id].compression_ratio = compression_ratio
            self.jobs[job_id].encoder_used = encoder_used
            self.jobs[job_id].elapsed_seconds = elapsed_seconds

    def fail_job(self, job_id: str, error_message: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "failed"
            self.jobs[job_id].error_message = error_message

    def update_job(self, job_id: str, **kwargs) -> None:
        if job_id in self.jobs:
            for k, v in kwargs.items():
                if hasattr(self.jobs[job_id], k):
                    setattr(self.jobs[job_id], k, v)

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        return [j for j in self.jobs.values() if j.status == "queued"][:limit]

    def list_jobs(self, limit: int = 50, status_filter: Optional[str] = None) -> List[CompressionJob]:
        jobs = list(self.jobs.values())
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        return jobs[:limit]

    def delete_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        queued = [j for j in self.jobs.values() if j.status == "queued"]
        return {"queue_position": 1, "queue_length": len(queued)}

    def count_queued(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "queued")

    def get_retention_summary(self) -> Dict[str, Any]:
        return {"retention_hours": 24, "last_cleanup_at": None, "last_cleanup_count": 0}


class TestCompressionService(unittest.TestCase):

    def test_create_and_get_compression_job(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)

        created = service.create_job(
            filename="video.mp4", input_path="/tmp/video.mp4", file_size_bytes=1000
        )
        self.assertIsNotNone(created.job_id)
        self.assertEqual(created.status, "queued")

        fetched = service.get_job(created.job_id)
        self.assertEqual(fetched.filename, "video.mp4")

    def test_get_job_or_none_returns_none_when_missing(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        result = service.get_job_or_none("nonexistent-id")
        self.assertIsNone(result)

    def test_create_job_with_params(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)

        created = service.create_job(
            filename="video.mp4", input_path="/tmp/video.mp4", file_size_bytes=5000,
            target_width=1280, bitrate_kbps=2000, crf=23, preset="fast",
            encoder="libx264", trim_start=5.0, trim_end=60.0,
            audio_extract_format="wav",
        )
        self.assertEqual(created.target_width, 1280)
        self.assertEqual(created.bitrate_kbps, 2000)
        self.assertEqual(created.audio_extract_format, "wav")
        self.assertEqual(created.trim_start, 5.0)

    def test_list_jobs_returns_all(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        service.create_job(filename="a.mp4", input_path="/tmp/a.mp4", file_size_bytes=100)
        service.create_job(filename="b.mp4", input_path="/tmp/b.mp4", file_size_bytes=200)
        jobs = service.list_jobs()
        self.assertEqual(len(jobs), 2)

    def test_list_jobs_with_status_filter(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        job = service.create_job(filename="a.mp4", input_path="/tmp/a.mp4", file_size_bytes=100)
        repo.update_job(job.job_id, status="completed")
        service.create_job(filename="b.mp4", input_path="/tmp/b.mp4", file_size_bytes=200)

        queued = service.list_jobs(status_filter="queued")
        self.assertEqual(len(queued), 1)
        completed = service.list_jobs(status_filter="completed")
        self.assertEqual(len(completed), 1)

    def test_count_queued(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        service.create_job(filename="a.mp4", input_path="/tmp/a.mp4", file_size_bytes=100)
        service.create_job(filename="b.mp4", input_path="/tmp/b.mp4", file_size_bytes=200)
        self.assertEqual(service.count_queued(), 2)

    def test_job_queue_info(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        job = service.create_job(filename="a.mp4", input_path="/tmp/a.mp4", file_size_bytes=100)
        info = service.job_queue_info(job.job_id)
        self.assertIn("queue_position", info)
        self.assertIn("queue_length", info)

    def test_get_retention_summary(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        summary = service.get_retention_summary()
        self.assertIn("retention_hours", summary)

    def test_delete_job(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        job = service.create_job(filename="a.mp4", input_path="/tmp/a.mp4", file_size_bytes=100)
        self.assertTrue(service.delete_job(job.job_id))
        self.assertIsNone(service.get_job_or_none(job.job_id))


if __name__ == "__main__":
    unittest.main()
