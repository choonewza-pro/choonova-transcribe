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
class TranscriptionJob:
    job_id: str
    filename: str
    file_size_bytes: int
    language: str  # 'th' | 'en' | 'auto'
    status: str    # 'queued' | 'processing' | 'completed' | 'failed'
    progress_pct: float = 0.0
    current_stage: str = "queued"
    total_chunks: int = 0
    completed_chunks: int = 0
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    result_text: Optional[str] = None
    timestamps_json: Optional[str] = None
    srt_text: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    chunks: List[JobChunk] = field(default_factory=list)
