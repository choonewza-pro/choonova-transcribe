"""
Transcription domain entities.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class JobChunk:
    chunk_index: int
    audio_path: str
    duration_seconds: float
    status: str = "pending"
    text: Optional[str] = None
    timestamps_json: Optional[str] = None


@dataclass
class TranscriptionRequest:
    """Validated/normalized transcription request parameters (pure value object).

    Produced by TranscriptionService.prepare_request() and consumed by the
    audio endpoints. Keeps request-level domain rules (language/model/
    speaker validation) out of the FastAPI delivery layer.
    """
    language: str
    model: Optional[str] = None
    enable_diarization: bool = False
    num_speakers: Optional[int] = None
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    with_timestamps: bool = False  # synchronous endpoint only


@dataclass
class TranscriptionJob:
    id: str
    filename: str
    file_size_bytes: int
    language: str  # 'th' | 'en' | 'auto'
    status: str    # 'queued' | 'processing' | 'completed' | 'failed'
    type: str = "transcription"
    model: Optional[str] = None
    progress: float = 0.0
    stage: str = "queued"
    total_chunks: int = 0
    completed_chunks: int = 0
    duration: float = 0.0
    processing_time: float = 0.0
    target_chunk_sec: float = 30.0
    max_chunk_sec: float = 60.0
    enable_diarization: bool = False
    with_timestamps: bool = False
    num_speakers: Optional[int] = None
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    chunks: List[JobChunk] = field(default_factory=list)
