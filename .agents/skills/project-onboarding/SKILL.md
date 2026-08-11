---
name: project-onboarding
description: Skill for onboarding developers to the Choonova Transcribe codebase architecture, workflows, and developer conventions.
---

# Project Onboarding Skill

This skill provides an introduction and guide for developers working on **Choonova Transcribe**.

## 📌 Overview

**Choonova Transcribe** is a Thai speech-to-text API service powered by **Typhoon ASR Realtime** (FastConformer-Transducer 114M) running on **Python 3.12 + FastAPI + NeMo**.

## 🏗️ Architecture & Core Components

- **Main Entrypoint:** `app/main.py` — FastAPI application, routes, WebSocket support, background task triggers.
- **Config & Settings:** `app/config.py` — Centralized environment settings.
- **Authentication:** `app/auth.py` — API key verification middleware & handlers.
- **Database Repository:** `app/db.py` — SQLite database for managing transcription job history.
- **ASR Engine:** `app/asr_engine.py` — Singleton wrapper around NVIDIA NeMo model.
- **Audio Processing:** `app/audio_utils.py` — Extraction, splitting, and format conversion via FFmpeg.
- **Job Processing Worker:** `app/job_worker.py` — Async pipeline for long-form transcription jobs.

## 🚀 Getting Started

### Local Execution
```bash
# GPU environment (CUDA required)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU environment
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
```

### Docker Execution
```bash
# GPU
docker compose up -d --build

# CPU
docker compose -f docker-compose-cpu.yml up -d --build
```

## 🛠️ Code Conventions & Workflow

- Always follow project git commit guidelines (`feat`, `fix`, `chore`, `docs`, `refactor`).
- Avoid saving files with mismatched character encodings (always ensure UTF-8 is used for Thai text).
