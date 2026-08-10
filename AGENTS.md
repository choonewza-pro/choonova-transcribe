<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->

# Typhoon ASR Transcribe Service

## Project Overview
Thai speech-to-text API service powered by **Typhoon ASR Realtime** (FastConformer-Transducer 114M) on **Python 3.12 + FastAPI + NeMo**. Runs on NVIDIA RTX 4080 (12GB VRAM). Supports REST, WebSocket real-time, and long-form video pipeline.

## Architecture
- **Entrypoint**: `app/main.py` — FastAPI app, route registration, WebSocket, periodic cleanup
- **Config**: `app/config.py` — reads env vars with defaults
- **Auth**: `app/auth.py` — API key verification (Bearer / x-api-key / ?api_key=)
- **DB**: `app/db.py` — SQLite repository for job history
- **ASR Engine**: `app/asr_engine.py` — NeMo model singleton wrapper
- **Audio Utils**: `app/audio_utils.py` — FFmpeg extract/split, disk-space check
- **Job Worker**: `app/job_worker.py` — async long-form transcription pipeline

## Commands
```bash
# GPU (requires CUDA)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830

# Docker
```bash
# GPU
docker compose up -d --build

# CPU (also works on Mac M1–M4)
docker compose -f docker-compose-cpu.yml up -d --build
```
```

## Test
No formal test suite exists. Manual verification via:
- Dashboard at `http://localhost:8830/`
- Syntax check: `python -m py_compile app/main.py app/db.py app/config.py app/audio_utils.py`
- cURL examples in README.md

## Key Files
- `requirements.txt` — GPU deps (CUDA 12.1 PyTorch index)
- `requirements-cpu.txt` — CPU deps (no PyTorch index)
- `Dockerfile` / `Dockerfile.cpu` — GPU/CPU Docker images
- `.env.example` — env template; copy to `.env` for local dev
- `model/` — `.nemo` weights (gitignored, auto-downloaded from HuggingFace)

## Convention Notes
- Model weights downloaded from `typhoon-ai/typhoon-asr-realtime` on HuggingFace
- `.nemo` files are gitignored
- `.env`, `.cache/`, `.agents/skills/`, `skills-lock.json` are gitignored
- Docker network `km4u-network` must exist: `docker network create km4u-network`
- Service port: `8830`