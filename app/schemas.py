from pydantic import BaseModel, Field
from typing import List, Optional, Any

class TimestampItem(BaseModel):
    word: str
    start: float
    end: float

class TranscribeResponse(BaseModel):
    status: str = "success"
    text: str
    duration_seconds: float
    elapsed_seconds: Optional[float] = None
    rtf: Optional[float] = None
    timestamps: Optional[List[TimestampItem]] = None

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "typhoon-asr-service"
    device: str

class JobCreateResponse(BaseModel):
    status: str = "accepted"
    job_id: str
    filename: str
    language: str = "th"
    message: str = "Job created and enqueued for background processing"

class JobStatusResponse(BaseModel):
    job_id: str
    filename: str
    file_size_bytes: int = 0
    language: str = "th"
    status: str
    progress_pct: float
    current_stage: str
    total_chunks: int = 0
    completed_chunks: int = 0
    duration_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    target_chunk_sec: float = 30.0
    max_chunk_sec: float = 60.0
    result_text: Optional[str] = None
    srt_text: Optional[str] = None
    timestamps: Optional[List[TimestampItem]] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str

class JobListItem(BaseModel):
    job_id: str
    filename: str
    status: str
    progress_pct: float
    current_stage: str
    created_at: str
