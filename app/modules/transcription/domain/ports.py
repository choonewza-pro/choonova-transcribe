"""
Transcription domain ports.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from app.modules.transcription.domain.entities import TranscriptionJob, JobChunk


class JobRepositoryPort(ABC):
    @abstractmethod
    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        pass

    @abstractmethod
    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, completed_chunks: int, elapsed_seconds: float) -> None:
        pass

    @abstractmethod
    def complete_job(self, job_id: str, result_text: str, timestamps_json: str, srt_text: str, elapsed_seconds: float) -> None:
        pass

    @abstractmethod
    def fail_job(self, job_id: str, error_message: str) -> None:
        pass

    @abstractmethod
    def update_status(
        self,
        job_id: str,
        status: str,
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
        pass

    @abstractmethod
    def list_jobs(self, limit: int = 50, offset: int = 0, status_filter: Optional[str] = None) -> List[TranscriptionJob]:
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


class ASREnginePort(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "th") -> Dict[str, Any]:
        """
        Transcribe an audio chunk file.
        Returns dict with keys: 'text', 'timestamps'
        """
        pass


class MediaProcessorPort(ABC):
    @abstractmethod
    def extract_and_chunk_audio(self, media_path: str, target_chunk_sec: float = 30.0) -> List[JobChunk]:
        """Extracts audio and splits into chunk files."""
        pass

    @abstractmethod
    def check_disk_space(self, path: str, required_gb: float = 5.0) -> bool:
        """Check available disk space at the given path."""
        pass

    @abstractmethod
    def safe_delete_dir(self, dir_path: str) -> bool:
        """Safely delete a directory and its contents."""
        pass

    @abstractmethod
    def get_duration(self, media_path: str) -> float:
        """Get media file duration in seconds."""
        pass


class ResourceGovernorPort(ABC):
    @abstractmethod
    def check_vram_and_offload_if_needed(self) -> None:
        """Checks VRAM availability and offloads idle models if VRAM is low."""
        pass
