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
    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[TranscriptionJob]:
        pass

    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
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


class ResourceGovernorPort(ABC):
    @abstractmethod
    def check_vram_and_offload_if_needed(self) -> None:
        """Checks VRAM availability and offloads idle models if VRAM is low."""
        pass
