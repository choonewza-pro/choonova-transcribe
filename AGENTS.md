<!-- headroom:rtk-instructions -->
# RTK — prefix every shell command with `rtk` (safe no-op passthrough; saves 60-90% tokens)
<!-- /headroom:rtk-instructions -->

# ChooNova Transcribe — Agent Reference

Thai speech-to-text API (Python 3.12, FastAPI, NeMo Typhoon ASR). Port **8830**.

## Prerequisites
- Docker network **km4u-network** must exist for `docker-compose-km4u.yml`: `docker network create km4u-network`
- `docker-compose.yml` (GPU, standalone) and `docker-compose-cpu.yml` (CPU, standalone) do NOT require it
- Model weights (~2GB) auto-downloaded from HuggingFace (`typhoon-ai/typhoon-asr-realtime`) at Docker build time; Whisper `medium` also pre-downloaded

## Commands
```bash
# GPU local
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU local (no --extra-index-url in reqs)
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830

# Docker GPU (standalone / km4u-network)
docker compose up -d --build
docker compose -f docker-compose-km4u.yml up -d --build

# Docker CPU
docker compose -f docker-compose-cpu.yml up -d --build

# Unit tests (unittest, NOT pytest)
python -m unittest discover -s tests/unit -t . -v

# Single test
python -m unittest tests.unit.settings.test_settings_service

# Syntax check
python -m py_compile app/main.py
```

## Test Architecture
- `unittest` (stdlib) — no pytest, no mocking library. Tests use `TestCase` with inline `Fake*Repository` classes implementing domain port ABCs (dict-backed).
- One test file per module under `tests/unit/<module>/`. Each follows Arrange-Act-Assert with constructor injection of fake repos.
- No `setUp`/`tearDown`, no async tests, no engine/media port fakes (those are subprocess-only).

## Architecture (Pragmatic Modular Hexagonal)
```
app/
├── core/                  # Cross-cutting: config (module-level, not Pydantic), WAL SQLite DB, HMAC security, exceptions, logging, media_validator, state
├── modules/
│   ├── settings/          # VRAM residency: domain/ -> application/ -> adapters/outbound/SQLiteSettingsRepository
│   ├── transcription/     # ASR jobs: domain/ -> application/ -> adapters/{inbound/workers/, outbound/{repositories/, media/, engines/}}
│   └── compression/       # Video compress: same structure
├── api/v1/                # FastAPI routers: transcription_router, compression_router, settings_router, realtime_router
└── api/web/               # Jinja2 dashboard (views_router.py)
```
- **Workers run as isolated subprocesses**: `sys.executable -m app.run_job <job_id> <path> <lang>`. Watchdog polls every 30s for crashes; marks jobs failed.
- **Worker subprocesses must lazy-import PyTorch/NeMo** (prevent RAM/VRAM leak at top level).
- **DI via FastAPI `Depends` factory functions** — no DI container. Engine/media ports are `None` in API endpoints (used only in subprocess workers).
- **`app/db.py` / `app/config.py` / `app/auth.py` are backward-compat shims** re-exporting from `app/core/`.

## Engines
- **Typhoon ASR** (`asr_engine.py`): Thai-only, NeMo FastConformer-Transducer 114M. ~1GB VRAM at FP16.
- **faster-whisper** (`whisper_engine.py`): English (`en`) or auto-detect (`auto`). Lazy-loaded on first request.
- **Routing**: `app/engine_router.py` dispatches by `normalize_language("th"|"en"|"auto")`.

## Model VRAM Mode
- `always` (default): models stay in VRAM once loaded.
- `idle`: unloaded after `MODEL_IDLE_TIMEOUT_SEC` (default 900s) of inactivity.
- Mode stored in SQLite `settings` table (seeded from env on first boot; editable at runtime via dashboard or `PUT /v1/settings/model` — no restart needed).

## API Auth
- `x-api-key` header, HMAC constant-time comparison via `Depends(verify_api_key)` on all v1 REST routes.
- Web UI (`/`, `/audio/transcribe`, etc.) and WebSocket = no auth.

## CUDA Resilience
- Transient errors: backoff + `clear_cuda_cache()` + retry (3 attempts, 5s backoff).
- Allocator corruption: `cudaDeviceReset` + model reload (via `engine_router.cuda_device_reset_all()`).
- Worker watchdog polls every 30s for crashed subprocesses (marks jobs failed, optionally deletes files via `WATCHDOG_DELETE_ON_CRASH`).
- `CUDA_RESET_BETWEEN_CHUNKS=true` resets CUDA context between long-form chunks.

## Key Files
- `requirements.txt` — GPU deps (CUDA 12.1 PyTorch index via `--extra-index-url`)
- `requirements-cpu.txt` — CPU deps (no PyTorch CUDA index)
- `.env.example` → copy to `.env`
- `model/typhoon-asr-realtime.nemo` — weights (gitignored, auto-downloaded from HuggingFace at Docker build time)
- `app/core/config.py` — all env vars defined here (module-level, not Pydantic Settings)
- `app/core/db.py` — SQLite WAL connection factory (used by all repositories)
- `knowledges/realtime-streaming-architecture.md` — deep-dive architecture docs
- `docker-compose.yml` / `docker-compose-km4u.yml` — GPU (standalone / with km4u-network)
- `docker-compose-cpu.yml` — CPU (no GPU deps)

## Gitignored
`.env`, `.cache/`, `data/choonova-transcribe.db`, `data/jobs/`, `*.nemo`, `.agents/skills/`, `.serena/`, `skills-lock.json`

## Style Notes
- **No `utils.py` / `helpers.py`** — FFmpeg work in `FFmpegAdapter`, filesystem work in `FilesystemAdapter`, audio logic in domain.
- **Group related use cases** in cohesive service files (no 1-file-per-class).
- Domain layer = pure Python `dataclasses` + ABC ports only — zero framework imports.
- Config = module-level constants (not Pydantic Settings).
- Healthcheck: `GET /healthz` (no auth, returns engine states).
- `MAX_UPLOAD_SIZE_MB=0` means unlimited (used for long-form jobs).