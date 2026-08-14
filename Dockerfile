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

# Upgrade pip and install huggingface_hub for model downloading
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir huggingface_hub

# Copy model download helper script
COPY scripts/download_models.py /app/scripts/download_models.py

# Download Typhoon ASR model weights into Docker image layer (Option 1: Docker Build-time Caching)
RUN python3 /app/scripts/download_models.py --typhoon

# Pre-download Whisper model (for English / Thai-English mixed support via faster-whisper)
ARG WHISPER_MODEL=large-v3-turbo
ARG HF_TOKEN=""
RUN python3 /app/scripts/download_models.py --whisper --whisper-model "${WHISPER_MODEL}" --hf-token "${HF_TOKEN}"

# Pre-download PyAnnote Diarization & SpeechBrain models (if HF_TOKEN is provided at build time)
RUN python3 /app/scripts/download_models.py --pyannote --hf-token "${HF_TOKEN}"

# Install all Python requirements with CUDA 12.1 index
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download WhisperX Forced Alignment model for English ('en')
RUN python3 /app/scripts/download_models.py --whisperx-align

COPY app /app/app

# Copy sample assets used by the API Endpoint Self-Test page (/test → /v1/tests/*)
COPY assets /app/assets

# Create empty SQLite jobs DB inside the image (no volume mount required).
# At runtime app/db.init_db() runs CREATE TABLE IF NOT EXISTS which is a no-op here.
RUN python3 -c "\
from app.db import init_db; \
init_db(); \
print('  ✅ EMPTY SQLite JOBS DB CREATED at /app/data/choonova-transcribe.db')"

EXPOSE 8830

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8830"]
