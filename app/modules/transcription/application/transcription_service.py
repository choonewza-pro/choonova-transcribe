"""
Application Service for managing ASR Transcription jobs.
Orchestrates job lifecycle: create, query, cancel, delete.
Worker subprocess spawning is handled at the router layer (inbound adapter concern).
"""

import uuid
from typing import Optional, List, Dict, Any
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

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        filename: str,
        file_size_bytes: int = 0,
        language: str = "th",
        target_chunk_sec: Optional[float] = None,
        max_chunk_sec: Optional[float] = None,
        job_id: Optional[str] = None,
        enable_diarization: bool = False,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        task: str = "transcribe",
        model: Optional[str] = None,
        type: str = "transcription",
    ) -> TranscriptionJob:
        """Create a new transcription job record (status=queued)."""
        final_job_id = job_id or str(uuid.uuid4())
        job = TranscriptionJob(
            id=final_job_id,
            type=type,
            model=model,
            filename=filename,
            file_size_bytes=file_size_bytes,
            language=language,
            status="queued",
            stage="queued",
            target_chunk_sec=target_chunk_sec if target_chunk_sec is not None else 30.0,
            max_chunk_sec=max_chunk_sec if max_chunk_sec is not None else 60.0,
            enable_diarization=enable_diarization,
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            task=task,
        )
        return self.repo.create_job(job)

    def get_job(self, job_id: str) -> TranscriptionJob:
        """Return job or raise NotFoundException."""
        job = self.repo.get_job(job_id)
        if not job:
            raise NotFoundException("TranscriptionJob", job_id)
        return job

    def get_job_or_none(self, job_id: str) -> Optional[TranscriptionJob]:
        """Return job or None (no exception)."""
        return self.repo.get_job(job_id)

    def list_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[str] = None,
    ) -> List[TranscriptionJob]:
        return self.repo.list_jobs(limit=limit, offset=offset, status_filter=status_filter)

    def delete_job(self, job_id: str) -> bool:
        return self.repo.delete_job(job_id)

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
        self.repo.update_status(
            job_id=job_id,
            status=status,
            progress=progress,
            stage=stage,
            completed_chunks=completed_chunks,
            total_chunks=total_chunks,
            duration=duration,
            processing_time=processing_time,
            result_json=result_json,
            error_json=error_json,
            model=model,
        )

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
    # Disk / media helpers (delegated to media_processor port)
    # ------------------------------------------------------------------

    def check_disk_space(self, path: str, required_gb: float = 5.0) -> bool:
        if self.media_processor:
            return self.media_processor.check_disk_space(path, required_gb)
        from app.audio_utils import check_disk_space
        return check_disk_space(path, required_gb)

    def safe_delete_dir(self, dir_path: str) -> bool:
        if self.media_processor:
            return self.media_processor.safe_delete_dir(dir_path)
        from app.audio_utils import safe_delete_dir
        return safe_delete_dir(dir_path)

    # ------------------------------------------------------------------
    # Inline transcription (short audio, synchronous)
    # ------------------------------------------------------------------

    def transcribe_bytes(self, audio_bytes: bytes, filename_hint: str, language: str) -> Dict[str, Any]:
        """Synchronous transcription of raw audio bytes via engine port (fast-path)."""
        if not self.engine:
            raise RuntimeError("ASREnginePort not configured on TranscriptionService")
        import tempfile, os
        suffix = os.path.splitext(filename_hint)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            return self.engine.transcribe(tmp_path, language)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Language normalization (delegates to legacy engine_router)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_language(language: str) -> str:
        from app.engine_router import normalize_language
        return normalize_language(language)

    # ------------------------------------------------------------------
    # SRT export helper
    # ------------------------------------------------------------------

    @staticmethod
    def build_srt_subtitles(segments: list) -> str:
        """Build SRT subtitle content from a list of timestamp segments."""
        from app.job_worker import build_srt_subtitles
        return build_srt_subtitles(segments)
