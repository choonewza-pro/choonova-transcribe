"""
Compression domain entities.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CompressionJob:
    job_id: str
    filename: str
    input_path: str
    file_size_bytes: int
    status: str
    # Compression parameters
    target_width: int = 0
    bitrate_kbps: int = 0
    crf: int = 28
    preset: str = "medium"
    encoder: str = "libx264"
    trim_start: float = 0.0
    trim_end: float = 0.0
    audio_extract_format: str = ""
    # Progress
    progress_pct: float = 0.0
    current_stage: str = "queued"
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    # Input metadata
    input_width: Optional[int] = None
    input_height: Optional[int] = None
    # Output metadata
    output_path: Optional[str] = None
    output_size_bytes: Optional[int] = None
    output_width: Optional[int] = None
    output_height: Optional[int] = None
    compression_ratio: Optional[float] = None
    encoder_used: Optional[str] = None
    audio_extract_path: Optional[str] = None
    audio_extract_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
