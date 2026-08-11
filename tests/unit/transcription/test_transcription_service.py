import unittest
from typing import Optional, List
from app.modules.transcription.domain.entities import TranscriptionJob
from app.modules.transcription.domain.ports import JobRepositoryPort
from app.modules.transcription.application.transcription_service import TranscriptionService


class FakeJobRepository(JobRepositoryPort):
    def __init__(self):
        self.jobs = {}

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        self.jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        return self.jobs.get(job_id)

    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, completed_chunks: int, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].progress_pct = progress_pct

    def complete_job(self, job_id: str, result_text: str, timestamps_json: str, srt_text: str, elapsed_seconds: float) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "completed"
            self.jobs[job_id].result_text = result_text

    def fail_job(self, job_id: str, error_message: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].status = "failed"

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[TranscriptionJob]:
        return list(self.jobs.values())[offset:offset+limit]

    def delete_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


class TestTranscriptionService(unittest.TestCase):

    def test_create_and_get_transcription_job(self):
        repo = FakeJobRepository()
        service = TranscriptionService(repo)
        
        created = service.create_job(filename="audio.wav", file_size_bytes=500, language="th")
        self.assertIsNotNone(created.job_id)
        self.assertEqual(created.status, "queued")
        self.assertEqual(created.language, "th")

        fetched = service.get_job(created.job_id)
        self.assertEqual(fetched.filename, "audio.wav")


if __name__ == "__main__":
    unittest.main()
