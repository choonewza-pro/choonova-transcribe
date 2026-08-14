from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any, Literal
from enum import Enum

class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class JobStage(str, Enum):
    queued = "queued"
    uploading = "uploading"
    extracting_audio = "extracting_audio"
    chunking = "chunking"
    transcribing = "transcribing"
    diarizing = "diarizing"
    building_result = "building_result"
    saving_result = "saving_result"
    cleanup = "cleanup"
    completed = "completed"

class JobError(BaseModel):
    code: str
    message: str
    retryable: bool = False

class TranscriptionSegment(BaseModel):
    text: Optional[str] = None
    word: Optional[str] = None
    start: float
    end: float
    speaker: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_text_and_word(cls, data: Any) -> Any:
        if isinstance(data, dict):
            text_val = data.get("text")
            word_val = data.get("word")
            if text_val is not None and word_val is None:
                data["word"] = str(text_val)
            elif word_val is not None and text_val is None:
                data["text"] = str(word_val)
        return data

class TranscriptionResult(BaseModel):
    text: str
    segments: Optional[List[TranscriptionSegment]] = None

class TimestampItem(BaseModel):
    word: Optional[str] = None
    text: Optional[str] = None
    start: float
    end: float
    speaker: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_word_and_text(cls, data: Any) -> Any:
        if isinstance(data, dict):
            word_val = data.get("word")
            text_val = data.get("text")
            if word_val is not None and text_val is None:
                data["text"] = str(word_val)
            elif text_val is not None and word_val is None:
                data["word"] = str(text_val)
        return data

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
    execution_device: str = "CPU"
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
    execution_device: str = "CPU"


class JobCreateResponse(BaseModel):
    status: str = "accepted"
    id: str
    filename: str
    language: str = "th"
    task: str = "transcribe"
    enable_diarization: bool = False
    num_speakers: Optional[int] = None
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    message: str = "Job created and enqueued for background processing"

class JobStatusResponse(BaseModel):
    id: str
    type: str = "transcription"
    filename: str
    file_size_bytes: int = 0
    language: str = "th"
    task: str = "transcribe"
    model: Optional[str] = None
    status: JobStatus
    stage: str
    progress: float
    total_chunks: int = 0
    completed_chunks: int = 0
    duration: float = 0.0
    processing_time: float = 0.0
    rtf: Optional[float] = None
    target_chunk_sec: float = 30.0
    max_chunk_sec: float = 60.0
    enable_diarization: bool = False
    num_speakers: Optional[int] = None
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    result: Optional[TranscriptionResult] = None
    error: Optional[JobError] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobListItem(BaseModel):
    id: str
    filename: str
    status: JobStatus
    progress: float
    stage: str
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


# =========================================================================
# OpenAI-Compatible Audio API Models
# =========================================================================

class ResponseFormat(str, Enum):
    """Supported response formats for OpenAI transcription / translation."""
    JSON = "json"
    TEXT = "text"
    SRT = "srt"
    VTT = "vtt"
    VERBOSE_JSON = "verbose_json"


class TimestampGranularity(str, Enum):
    """Timestamp granularity options for verbose_json."""
    WORD = "word"
    SEGMENT = "segment"


class OpenAITranscriptionWord(BaseModel):
    """Word-level timestamp object for verbose_json."""
    word: str
    start: float
    end: float


class OpenAITranscriptionSegment(BaseModel):
    """Segment-level object for verbose_json."""
    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: List[int] = Field(default_factory=list)
    temperature: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 0.0
    no_speech_prob: float = 0.0


class OpenAITranscriptionJsonResponse(BaseModel):
    """Simple JSON response format (OpenAI default)."""
    text: str


class OpenAITranscriptionVerboseJsonResponse(BaseModel):
    """Verbose JSON response with segments and optional words."""
    task: Literal["transcribe", "translate"]
    language: str
    duration: float
    text: str
    segments: List[OpenAITranscriptionSegment] = Field(default_factory=list)
    words: Optional[List[OpenAITranscriptionWord]] = None


class OpenAIErrorDetail(BaseModel):
    """Error detail matching OpenAI format."""
    message: str
    type: str = "invalid_request_error"
    param: Optional[str] = None
    code: Optional[str] = None


class OpenAIErrorResponse(BaseModel):
    """Error response matching OpenAI format."""
    error: OpenAIErrorDetail

