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
    id: str
    type: str = "transcription"
    filename: str
    file_size_bytes: int
    language: str  # 'th' | 'en' | 'auto'
    model: Optional[str] = None
    status: str    # 'queued' | 'processing' | 'completed' | 'failed'
    progress: float = 0.0
    stage: str = "queued"
    total_chunks: int = 0
    completed_chunks: int = 0
    duration: float = 0.0
    processing_time: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    chunks: List[JobChunk] = field(default_factory=list)
