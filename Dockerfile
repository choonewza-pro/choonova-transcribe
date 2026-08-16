# =========================================================================
# GPU Dockerfile for Typhoon ASR Realtime Service (Python 3.12 Slim + CUDA 12.1)
# =========================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Install all Python requirements with CUDA 12.1 index
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy model download helper script
COPY scripts/download_models.py /app/scripts/download_models.py

# Bake any models already present in ./models into the image (fast, offline).
# The download steps below are skip-aware: each model found here is not re-downloaded,
# only the missing ones are fetched. On a fresh clone with no weights this just
# copies the tracked configs, then downloads fill the rest.
# COPY models /app/models  # DEV: use volume mount in docker-compose instead

ARG WHISPER_MODEL=deepdml/faster-whisper-large-v3-turbo-ct2
ARG HF_TOKEN=""

# Download Typhoon ASR model weights into Docker image layer (Option 1: Docker Build-time Caching)
RUN python3 /app/scripts/download_models.py --typhoon --hf-token "${HF_TOKEN}"

# Pre-download Whisper model (for English / Thai-English mixed support via faster-whisper)
RUN python3 /app/scripts/download_models.py --whisper --whisper-model "${WHISPER_MODEL}" --hf-token "${HF_TOKEN}"

# Pre-download Thai-tuned Whisper model (for accurate Thai offline path via faster-whisper CT2)
ARG WHISPER_THAI_MODEL=Avocaduu14/whisper-th-large-v3-ct2
RUN WHISPER_THAI_MODEL="${WHISPER_THAI_MODEL}" python3 /app/scripts/download_models.py --whisper-thai --hf-token "${HF_TOKEN}"

# Pre-download PyAnnote Diarization & SpeechBrain models (if HF_TOKEN is provided at build time)
RUN python3 /app/scripts/download_models.py --pyannote --hf-token "${HF_TOKEN}"

# Pre-download WhisperX Forced Alignment model for English ('en')
RUN python3 /app/scripts/download_models.py --whisperx-align

COPY app /app/app

# Copy sample assets used by the API Endpoint Self-Test page (/test → /v1/tests/*)
COPY assets /app/assets

# NOTE: The SQLite jobs DB is intentionally NOT created at build time.
# Building it here would seed the `settings` table with build-time env
# defaults (MODEL_LOAD_MODE etc.) that the runtime container env cannot
# override (init_db uses INSERT OR IGNORE). Let runtime init_db() create
# it so the container's .env-driven settings are honored.

EXPOSE 8830

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8830"]
