from pydantic import BaseModel, Field
from typing import List, Optional, Any, Literal

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
    model_load_mode: str = "always"
    model_idle_timeout_sec: float = 900.0
    typhoon_model_state: str = "idle"
    whisper_model_state: str = "idle"

class ModelSettings(BaseModel):
    mode: Literal["always", "idle"]
    idle_timeout_sec: float = Field(gt=0, description="Idle timeout in seconds before unloading the model in 'idle' mode")

class ModelSettingsResponse(BaseModel):
    mode: str
    idle_timeout_sec: float
    typhoon_model_state: str
    whisper_model_state: str

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

class CompressJobCreateResponse(BaseModel):
    status: str = "accepted"
    job_id: str
    filename: str
    queue_position: int = 1
    queue_length: int = 0
    message: str = "Job created and enqueued for background video compression"

class CompressJobStatusResponse(BaseModel):
    job_id: str
    filename: str
    file_size_bytes: int = 0
    status: str
    progress_pct: float
    current_stage: str
    target_width: int = 0
    bitrate_kbps: int = 0
    crf: int = 28
    preset: str = "medium"
    encoder: str = "libx264"
    trim_start: float = 0.0
    trim_end: float = 0.0
    input_width: int = 0
    input_height: int = 0
    duration_seconds: float = 0.0
    output_path: Optional[str] = None
    output_size_bytes: int = 0
    output_width: int = 0
    output_height: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
    queue_position: int = 0
    queue_length: int = 0
    audio_extract_format: str = ""
    audio_extract_path: Optional[str] = None
    audio_extract_size_bytes: int = 0
    audio_exists: bool = False
    created_at: str
    updated_at: str
