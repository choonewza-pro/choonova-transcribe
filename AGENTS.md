<!-- headroom:rtk-instructions -->
# RTK — prefix every shell command with `rtk` (safe no-op passthrough; saves 60-90% tokens)
<!-- /headroom:rtk-instructions -->

# ChooNova Transcribe — Agent Reference

Thai speech-to-text API (Python 3.12, FastAPI, NeMo Typhoon ASR). Port **8830**. Docker network **km4u-network** must exist: `docker network create km4u-network`

## Commands
```bash
# GPU local
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU local
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830

# Docker GPU / CPU
docker compose up -d --build
docker compose -f docker-compose-cpu.yml up -d --build

# Unit tests (unittest, NOT pytest)
python -m unittest discover -s tests/unit -t . -v

# Single test
python -m unittest tests.unit.settings.test_settings_service

# Syntax check
python -m py_compile app/main.py
```

## Test Architecture
- `unittest` (stdlib) — no pytest. Tests use `TestCase` with inline `Fake*Repository` classes implementing domain port ABCs (dict-backed, no mocking library).
- One test file per module under `tests/unit/<module>/`.

## Architecture (Pragmatic Modular Hexagonal)
```
app/
├── core/                  # Cross-cutting: config, db (WAL SQLite), security (x-api-key HMAC), exceptions, logging
├── modules/
│   ├── settings/          # VRAM residency mode: domain -> application -> adapters/outbound/SQLiteSettingsRepository
│   ├── transcription/     # ASR jobs: domain -> application -> adapters/{inbound/workers/run_job.py, outbound/{repositories/, media/, engines/}}
│   └── compression/       # Video compress: domain -> application -> adapters/{inbound/workers/run_compress_job.py, outbound/}
├── api/v1/                # FastAPI routers: transcription_router, compression_router, settings_router, realtime_router
└── api/web/               # HTML dashboard (views_router.py, Jinja2)
```
- **Workers run as isolated subprocesses**: `sys.executable -m app.run_job <job_id> <path> <lang>`. Watchdog detects crashes.
- **Worker subprocesses must lazy-import PyTorch/NeMo** (prevent RAM/VRAM leak at top level).
- **Heavy DI via FastAPI `Depends` factory functions** — no DI container. Services receive repo adapters; engine/media ports are `None` in API endpoints (used only in subprocess workers).
- **`app/db.py` / `app/config.py` / `app/auth.py` are backward-compat shims** that re-export from `app/core/`.

## Engines
- **Typhoon ASR** (`typhoon-adapter`): Thai-only, NeMo FastConformer-Transducer 114M. ~1GB VRAM at FP16. Faster than Whisper for Thai.
- **faster-whisper** (`whisper-adapter`): English (`en`) or auto-detect (`auto`). Lazy-loaded on first `en`/`auto` request.
- **Routing**: `app/engine_router.py` dispatches by language. `normalize_language("th"|"en"|"auto")`.

## Model VRAM Mode
- `always` (default): models stay in VRAM once loaded.
- `idle`: unloaded after `MODEL_IDLE_TIMEOUT_SEC` (default 900s) of inactivity.
- Mode stored in SQLite `settings` table (seeded from env on first boot; editable at runtime via `/setting` or `PUT /v1/settings/model`).

## API Auth
- `x-api-key` header, HMAC constant-time comparison. Applied via `Depends(verify_api_key)` on all v1 REST routes.
- Web UI (`/`, `/audio/transcribe`, etc.) = no auth.
- WebSocket = no auth (would need query-param handshake).

## CUDA Resilience
- Transient errors: backoff + `clear_cuda_cache()` + retry (3 attempts, 5s backoff).
- Allocator corruption: `cudaDeviceReset` + model reload.
- Worker watchdog: polls every 30s for crashed subprocesses (marks jobs failed).
- `CUDA_RESET_BETWEEN_CHUNKS=true` (env) resets CUDA context between long-form chunks.

## Key Files
- `requirements.txt` — GPU deps (CUDA 12.1 PyTorch index)
- `requirements-cpu.txt` — CPU deps
- `.env.example` → copy to `.env`
- `model/typhoon-asr-realtime.nemo` — weights (gitignored, auto-downloaded from HuggingFace)
- `app/core/config.py` — all env vars defined here
- `app/core/db.py` — SQLite WAL connection factory (used by all repositories)

## Gitignored
`.env`, `.cache/`, `data/choonova-transcribe.db`, `*.nemo`, `.agents/skills/`, `.serena/`, `skills-lock.json`

## Style Notes
- **No `utils.py` / `helpers.py`** — put FFmpeg work in `FFmpegAdapter`, filesystem work in `FilesystemAdapter`, audio logic in domain.
- **Group related use cases** in cohesive service files (no 1-file-per-class).
- Domain layer = pure Python `dataclasses` + ABC ports only — zero framework imports.
- Config = module-level constants (not Pydantic Settings).