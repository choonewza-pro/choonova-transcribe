"""
Application Service for managing ASR Transcription jobs.
"""

import os
import uuid
from typing import Optional, List
from app.modules.transcription.domain.entities import TranscriptionJob
from app.modules.transcription.domain.ports import JobRepositoryPort, ASREnginePort, MediaProcessorPort
from app.core.exceptions import NotFoundException


class TranscriptionService:
    """Orchestrates audio/video transcription use cases."""

    def __init__(
        self,
        repo: JobRepositoryPort,
        engine: Optional[ASREnginePort] = None,
        media_processor: Optional[MediaProcessorPort] = None,
    ):
        self.repo = repo
        self.engine = engine
        self.media_processor = media_processor

    def create_job(self, filename: str, file_size_bytes: int = 0, language: str = "th") -> TranscriptionJob:
        job_id = str(uuid.uuid4())
        job = TranscriptionJob(
            job_id=job_id,
            filename=filename,
            file_size_bytes=file_size_bytes,
            language=language,
            status="queued",
            current_stage="queued",
        )
        return self.repo.create_job(job)

    def get_job(self, job_id: str) -> TranscriptionJob:
        job = self.repo.get_job(job_id)
        if not job:
            raise NotFoundException("TranscriptionJob", job_id)
        return job

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[TranscriptionJob]:
        return self.repo.list_jobs(limit=limit, offset=offset)

    def delete_job(self, job_id: str) -> bool:
        return self.repo.delete_job(job_id)
