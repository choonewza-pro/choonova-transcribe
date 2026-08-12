"""
Application Service for managing video compression jobs.
Orchestrates job lifecycle: create, query, cancel, delete.
Worker subprocess spawning is handled at the router layer (inbound adapter concern).
"""

import uuid
from typing import Optional, List, Dict, Any
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort, MediaCompressorPort
from app.core.exceptions import NotFoundException


class CompressionService:
    """Orchestrates video compression use cases."""

    def __init__(
        self,
        repo: CompressionRepositoryPort,
        compressor: Optional[MediaCompressorPort] = None,
    ):
        self.repo = repo
        self.compressor = compressor

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        filename: str,
        input_path: str,
        file_size_bytes: int = 0,
        target_width: int = 0,
        bitrate_kbps: int = 0,
        crf: int = 28,
        preset: str = "medium",
        encoder: str = "libx264",
        trim_start: float = 0.0,
        trim_end: float = 0.0,
        audio_extract_format: str = "",
        job_id: Optional[str] = None,
    ) -> CompressionJob:
        """Create a new compression job record (status=queued)."""
        final_job_id = job_id or str(uuid.uuid4())
        job = CompressionJob(
            job_id=final_job_id,
            filename=filename,
            input_path=input_path,
            file_size_bytes=file_size_bytes,
            status="queued",
            current_stage="Waiting in queue",
            target_width=target_width,
            bitrate_kbps=bitrate_kbps,
            crf=crf,
            preset=preset,
            encoder=encoder,
            trim_start=trim_start,
            trim_end=trim_end,
            audio_extract_format=audio_extract_format,
        )
        return self.repo.create_job(job)

    def get_job(self, job_id: str) -> CompressionJob:
        """Return job or raise NotFoundException."""
        job = self.repo.get_job(job_id)
        if not job:
            raise NotFoundException("CompressionJob", job_id)
        return job

    def get_job_or_none(self, job_id: str) -> Optional[CompressionJob]:
        """Return job or None (no exception)."""
        return self.repo.get_job(job_id)

    def list_jobs(self, limit: int = 50, status_filter: Optional[str] = None) -> List[CompressionJob]:
        return self.repo.list_jobs(limit=limit, status_filter=status_filter)

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        return self.repo.get_queued_jobs(limit=limit)

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job_or_none(job_id)
        if job and job.output_path:
            import os
            try:
                if os.path.exists(job.output_path):
                    os.remove(job.output_path)
            except OSError:
                pass
        if job and job.audio_extract_path:
            import os
            try:
                if os.path.exists(job.audio_extract_path):
                    os.remove(job.audio_extract_path)
            except OSError:
                pass
        return self.repo.delete_job(job_id)

    def update_job(self, job_id: str, **kwargs) -> None:
        """General-purpose field update (mirrors legacy update_compress_job)."""
        self.repo.update_job(job_id, **kwargs)

    # ------------------------------------------------------------------
    # Queue / dashboard helpers
    # ------------------------------------------------------------------

    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        return self.repo.job_queue_info(job_id)

    def count_queued(self) -> int:
        return self.repo.count_queued()

    def get_retention_summary(self) -> Dict[str, Any]:
        return self.repo.get_retention_summary()

    # ------------------------------------------------------------------
    # Disk / directory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def check_disk_space(path: str, required_gb: float = 5.0) -> bool:
        from app.audio_utils import check_disk_space
        return check_disk_space(path, required_gb)

    @staticmethod
    def safe_delete_dir(dir_path: str) -> bool:
        from app.audio_utils import safe_delete_dir
        return safe_delete_dir(dir_path)

    # ------------------------------------------------------------------
    # Parameter helpers (mirrors legacy compress_utils)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_encoder(encoder: str) -> str:
        from app.compress_utils import normalize_encoder
        return normalize_encoder(encoder)

    @staticmethod
    def parse_trim_time(value: str) -> float:
        from app.compress_utils import parse_trim_time
        return parse_trim_time(value)
