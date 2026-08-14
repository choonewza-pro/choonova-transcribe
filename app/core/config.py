"""
Core application configuration reading environment variables.
"""

import os
import torch
from dotenv import load_dotenv

# Load .env BEFORE reading any environment variables so that local runs
# (uvicorn app.main:app) behave the same as Docker Compose, which already
# interpolates .env into the container. OS env vars still take precedence
# (load_dotenv defaults to override=False).
load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8830"))
DEFAULT_GATEWAY_API_KEY = "change-me-in-production"
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", DEFAULT_GATEWAY_API_KEY)
# True when the admin has not yet replaced the shipped default API key.
GATEWAY_API_KEY_IS_DEFAULT = GATEWAY_API_KEY == DEFAULT_GATEWAY_API_KEY
MODEL_PATH = os.getenv("MODEL_PATH", "models/typhoon-asr-realtime.nemo")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")

# Directory & Database Configurations
# BASE_DIR is the app/ directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(SERVICE_DIR, "data"))
JOBS_DB_PATH = os.path.join(DATA_DIR, "choonova-transcribe.db")
TEMP_JOBS_DIR = os.getenv("TEMP_JOBS_DIR", "/tmp/choonova-transcribe-jobs")

# Optimize PyTorch CUDA Caching Allocator memory management
if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# Operational Limits
MIN_FREE_DISK_GB = float(os.getenv("MIN_FREE_DISK_GB", "5.0"))
TRANSCRIBE_RETENTION_HOURS = int(os.getenv("TRANSCRIBE_RETENTION_HOURS", "24"))
TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC = float(os.getenv("TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC", "45.0"))
TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC = float(os.getenv("TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC", "90.0"))
TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC = float(os.getenv("TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC", "25.0"))
TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC = float(os.getenv("TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC", "30.0"))
TRANSCRIBE_MAX_CONCURRENT = int(os.getenv("TRANSCRIBE_MAX_CONCURRENT", "1"))
TRANSCRIBE_MAX_QUEUED = int(os.getenv("TRANSCRIBE_MAX_QUEUED", "10"))
# Max upload size for long-form media jobs in MB; 0 = unlimited.
MAX_UPLOAD_SIZE_MB = float(os.getenv("MAX_UPLOAD_SIZE_MB", "0"))
# Max upload size for the short audio endpoint in MB; always enforced (must be > 0).
MAX_AUDIO_UPLOAD_SIZE_MB = float(os.getenv("MAX_AUDIO_UPLOAD_SIZE_MB", "50.0"))
# Max duration in seconds for uploaded media to prevent GPU hogging (0 = unlimited, default 21600 = 6 hours)
MAX_MEDIA_DURATION_SEC = float(os.getenv("MAX_MEDIA_DURATION_SEC", "21600.0"))

# =========================================================================
# Video Compressor (FFmpeg) configuration
# =========================================================================
COMPRESS_ENCODER = os.getenv("COMPRESS_ENCODER", "libx264").strip().lower()
COMPRESS_PRESET = os.getenv("COMPRESS_PRESET", "medium")
COMPRESS_CRF = int(os.getenv("COMPRESS_CRF", "28"))
COMPRESS_MAX_CONCURRENT = int(os.getenv("COMPRESS_MAX_CONCURRENT", "1"))
COMPRESS_MAX_QUEUED = int(os.getenv("COMPRESS_MAX_QUEUED", "10"))
COMPRESS_RETENTION_HOURS = float(os.getenv("COMPRESS_RETENTION_HOURS", "24"))
COMPRESS_OUTPUT_DIR = os.getenv("COMPRESS_OUTPUT_DIR", TEMP_JOBS_DIR)

# Auto-detect CUDA availability
requested_device = os.getenv("DEVICE", "cuda").lower()
if requested_device == "cuda" and torch.cuda.is_available():
    DEVICE = "cuda"
else:
    DEVICE = "cpu"

# Limit PyTorch CPU threads to prevent thread over-subscription / CPU thrashing in CPU mode
if DEVICE == "cpu":
    try:
        cpu_threads = int(os.getenv("TORCH_THREAD_LIMIT", "4"))
        torch.set_num_threads(cpu_threads)
        os.environ["OMP_NUM_THREADS"] = str(cpu_threads)
        os.environ["MKL_NUM_THREADS"] = str(cpu_threads)
        os.environ["OPENBLAS_NUM_THREADS"] = str(cpu_threads)
        os.environ["VECLIB_MAXIMUM_THREADS"] = str(cpu_threads)
        os.environ["NUMEXPR_NUM_THREADS"] = str(cpu_threads)
    except Exception:
        pass

# Model VRAM residency mode defaults
MODEL_LOAD_MODE_DEFAULT = os.getenv("MODEL_LOAD_MODE", "always").lower()
MODEL_IDLE_TIMEOUT_SEC_DEFAULT = float(os.getenv("MODEL_IDLE_TIMEOUT_SEC", "900"))

# Whisper secondary engine for English / Thai-English mixed audio
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
WHISPER_COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip() or None
SUPPORTED_LANGUAGES = ("th", "en", "auto")

# Speaker Diarization configurations (PyAnnote 3.1 & WhisperX)
DIARIZATION_ENABLED = os.getenv("DIARIZATION_ENABLED", "true").lower() in ("true", "1", "yes")
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
DIARIZATION_MIN_SPEAKERS = int(os.getenv("DIARIZATION_MIN_SPEAKERS", "") or 0) or None
DIARIZATION_MAX_SPEAKERS = int(os.getenv("DIARIZATION_MAX_SPEAKERS", "") or 0) or None

# Public share configurations for history pages
ALLOW_ACCESS_TRANSCRIBE_HISTORY = os.getenv("ALLOW_ACCESS_TRANSCRIBE_HISTORY", "false").lower() in ("true", "1", "yes")
ALLOW_ACCESS_COMPRESS_HISTORY = os.getenv("ALLOW_ACCESS_COMPRESS_HISTORY", "false").lower() in ("true", "1", "yes")

# =========================================================================
# API Endpoint Self-Test (/v1/tests/*)
# =========================================================================
# Max wall-clock seconds to wait for an async transcription job to reach a
# terminal status before the test is marked FAILED (cleanup still runs).
APITEST_TRANSCRIBE_MAX_WAIT_SEC = int(os.getenv("APITEST_TRANSCRIBE_MAX_WAIT_SEC", "1800"))
# Max wall-clock seconds to wait for an async compression job to reach a
# terminal status before the test is marked FAILED (cleanup still runs).
APITEST_COMPRESS_MAX_WAIT_SEC = int(os.getenv("APITEST_COMPRESS_MAX_WAIT_SEC", "3600"))
# Polling interval (seconds) while waiting for async jobs during self-test.
APITEST_POLL_INTERVAL_SEC = float(os.getenv("APITEST_POLL_INTERVAL_SEC", "5"))


def get_real_execution_device() -> str:
    """
    Detect actual compute device (CPU or GPU) at runtime using PyTorch CUDA check
    and active GPU device name, rather than relying solely on the DEVICE env variable.
    """
    if DEVICE == "cuda":
        try:
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                return f"GPU ({gpu_name})" if gpu_name else "GPU"
        except Exception:
            pass
        return "CPU (CUDA Unavailable)"
    return "CPU"

