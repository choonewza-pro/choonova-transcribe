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

# Upgrade pip and install all Python requirements with CUDA 12.1 index
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Download model weights into Docker image layer (Option 1: Docker Build-time Caching)
RUN python3 -c "\
from huggingface_hub import hf_hub_download; \
import os; \
p = hf_hub_download(repo_id='typhoon-ai/typhoon-asr-realtime', filename='typhoon-asr-realtime.nemo', local_dir='/app/model'); \
size = os.path.getsize(p) / (1024**3); \
print(); \
print('=' * 70); \
print('  ✅ MODEL DOWNLOAD COMPLETE — Typhoon ASR Realtime'); \
print(f'  📁 {p}'); \
print(f'  💾 {size:.2f} GB'); \
print('=' * 70); \
print()"

# Pre-download Whisper model (for English / Thai-English mixed support via faster-whisper)
ARG WHISPER_MODEL=medium
RUN python3 -c "\
from huggingface_hub import snapshot_download; \
import os; \
p = snapshot_download(repo_id='Systran/faster-whisper-' + os.getenv('WHISPER_MODEL', 'medium')); \
print(); \
print('=' * 70); \
print('  ✅ WHISPER MODEL DOWNLOAD COMPLETE — faster-whisper-' + os.getenv('WHISPER_MODEL', 'medium')); \
print(f'  📁 {p}'); \
print('=' * 70); \
print()"

COPY app /app/app

# Create empty SQLite jobs DB inside the image (no volume mount required).
# At runtime app/db.init_db() runs CREATE TABLE IF NOT EXISTS which is a no-op here.
RUN python3 -c "\
from app.db import init_db; \
init_db(); \
print('  ✅ EMPTY SQLite JOBS DB CREATED at /app/data/jobs.db')"

EXPOSE 8830

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8830"]
