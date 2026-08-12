"""
Compression domain ports.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from app.modules.compression.domain.entities import CompressionJob


class CompressionRepositoryPort(ABC):
    @abstractmethod
    def create_job(self, job: CompressionJob) -> CompressionJob:
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[CompressionJob]:
        pass

    @abstractmethod
    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, elapsed_seconds: float) -> None:
        pass

    @abstractmethod
    def complete_job(self, job_id: str, output_path: str, output_size_bytes: int, compression_ratio: float, encoder_used: str, elapsed_seconds: float) -> None:
        pass

    @abstractmethod
    def fail_job(self, job_id: str, error_message: str) -> None:
        pass

    @abstractmethod
    def update_job(self, job_id: str, **kwargs) -> None:
        """General-purpose field update (mirrors legacy update_compress_job)."""
        pass

    @abstractmethod
    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        pass

    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
        pass

    @abstractmethod
    def job_queue_info(self, job_id: str) -> Dict[str, int]:
        pass

    @abstractmethod
    def count_queued(self) -> int:
        pass

    @abstractmethod
    def get_retention_summary(self) -> Dict[str, Any]:
        pass


class MediaCompressorPort(ABC):
    @abstractmethod
    def compress_video(
        self,
        input_path: str,
        output_path: str,
        target_resolution: Optional[str] = None,
        encoder: str = "libx264",
        preset: str = "medium",
        crf: int = 28,
        progress_callback=None,
    ) -> dict:
        pass
