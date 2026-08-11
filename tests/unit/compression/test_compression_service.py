import unittest
from typing import Optional, List
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort
from app.modules.compression.application.compression_service import CompressionService


class FakeCompressRepository(CompressionRepositoryPort):
    def __init__(self):
        self.jobs = {}

    def create_job(self, job: CompressionJob) -> CompressionJob:
        self.jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[CompressionJob]:
        return self.jobs.get(job_id)

    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].progress_pct = progress_pct
            self.jobs[job_id].current_stage = current_stage

    def complete_job(self, job_id: str, output_path: str, output_size_bytes: int, compression_ratio: float, encoder_used: str, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "completed"
            self.jobs[job_id].output_path = output_path

    def fail_job(self, job_id: str, error_message: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "failed"

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        return [j for j in self.jobs.values() if j.status == "queued"][:limit]

    def delete_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


class TestCompressionService(unittest.TestCase):

    def test_create_and_get_compression_job(self):
        repo = FakeCompressRepository()
        service = CompressionService(repo)
        
        created = service.create_job(filename="video.mp4", input_path="/tmp/video.mp4", file_size_bytes=1000)
        self.assertIsNotNone(created.job_id)
        self.assertEqual(created.status, "queued")

        fetched = service.get_job(created.job_id)
        self.assertEqual(fetched.filename, "video.mp4")


if __name__ == "__main__":
    unittest.main()
