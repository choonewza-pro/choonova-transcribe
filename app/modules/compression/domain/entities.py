"""
Compression domain entities.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class CompressionJob:
    job_id: str
    filename: str
    input_path: str
    file_size_bytes: int
    status: str
    progress_pct: float = 0.0
    current_stage: str = "pending"
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    output_path: Optional[str] = None
    output_size_bytes: Optional[int] = None
    compression_ratio: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    bitrate_kbps: Optional[float] = None
    fps: Optional[float] = None
    encoder_used: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
