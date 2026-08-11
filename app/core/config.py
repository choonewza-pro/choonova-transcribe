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
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "change-me-in-production")
MODEL_PATH = os.getenv("MODEL_PATH", "model/typhoon-asr-realtime.nemo")
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
CLEANUP_RETENTION_HOURS = int(os.getenv("CLEANUP_RETENTION_HOURS", "24"))
TARGET_CHUNK_DURATION_SEC = float(os.getenv("TARGET_CHUNK_DURATION_SEC", "30.0"))
MAX_CHUNK_DURATION_SEC = float(os.getenv("MAX_CHUNK_DURATION_SEC", "60.0"))
# Max upload size for long-form media jobs in MB; 0 = unlimited.
MAX_UPLOAD_SIZE_MB = float(os.getenv("MAX_UPLOAD_SIZE_MB", "0"))
# Max upload size for the short audio endpoint in MB; always enforced (must be > 0).
MAX_AUDIO_UPLOAD_SIZE_MB = float(os.getenv("MAX_AUDIO_UPLOAD_SIZE_MB", "50.0"))

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

# Model VRAM residency mode defaults
MODEL_LOAD_MODE_DEFAULT = os.getenv("MODEL_LOAD_MODE", "always").lower()
MODEL_IDLE_TIMEOUT_SEC_DEFAULT = float(os.getenv("MODEL_IDLE_TIMEOUT_SEC", "900"))

# Whisper secondary engine for English / Thai-English mixed audio
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"
SUPPORTED_LANGUAGES = ("th", "en", "auto")
