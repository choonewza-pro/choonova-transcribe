"""
Application Service for managing video compression jobs.
"""

import os
import uuid
from typing import Optional, List
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort, MediaCompressorPort
from app.core.exceptions import NotFoundException, ValidationException


class CompressionService:
    """Orchestrates video compression use cases."""

    def __init__(self, repo: CompressionRepositoryPort, compressor: Optional[MediaCompressorPort] = None):
        self.repo = repo
        self.compressor = compressor

    def create_job(self, filename: str, input_path: str, file_size_bytes: int = 0) -> CompressionJob:
        job_id = str(uuid.uuid4())
        job = CompressionJob(
            job_id=job_id,
            filename=filename,
            input_path=input_path,
            file_size_bytes=file_size_bytes,
            status="queued",
            current_stage="queued",
        )
        return self.repo.create_job(job)

    def get_job(self, job_id: str) -> CompressionJob:
        job = self.repo.get_job(job_id)
        if not job:
            raise NotFoundException("CompressionJob", job_id)
        return job

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job.output_path and os.path.exists(job.output_path):
            try:
                os.remove(job.output_path)
            except OSError:
                pass
        if getattr(job, "audio_extract_path", None) and os.path.exists(job.audio_extract_path):
            try:
                os.remove(job.audio_extract_path)
            except OSError:
                pass
        return self.repo.delete_job(job_id)

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        return self.repo.get_queued_jobs(limit=limit)
