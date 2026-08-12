<!-- headroom:rtk-instructions -->
# RTK — prefix every shell command with `rtk` (safe no-op passthrough; saves 60-90% tokens)
<!-- /headroom:rtk-instructions -->

# ChooNova Transcribe — Agent Reference

Thai speech-to-text API (Python 3.12, FastAPI, NeMo Typhoon ASR, faster-whisper). Port **8830**.

## Commands
```bash
# GPU local
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU local
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830

# Docker GPU
docker compose up -d --build
docker compose -f docker-compose-km4u.yml up -d --build   # requires: docker network create km4u-network

# Docker CPU
docker compose -f docker-compose-cpu.yml up -d --build

# Tests (unittest, NOT pytest — no mocking lib)
python -m unittest discover -s tests/unit -t . -v
python -m unittest tests.unit.settings.test_settings_service

# Syntax check
python -m py_compile app/main.py
```

## Critical: Dual Architecture

This project is **mid-migration** from monolithic (`app/db.py`, `app/engine_router.py`, `app/job_worker.py`) to hexagonal modules (`app/modules/`). **BOTH paths coexist**:

| Code path | Who uses it |
|-----------|-------------|
| **Monolithic** (`app/db.py`, `app/engine_router.py`, `app/job_worker.py`, `app/compress_worker.py`) | Worker subprocesses (`python -m app.run_job`), `main.py` background tasks (watchdog, cleanup, model idle reaper, compress queue dispatcher), legacy `main.py` endpoints |
| **Hexagonal** (`app/modules/<module>/` domain/application/adapters) | FastAPI routers (`app/api/v1/*_router.py`) via service factory functions |

**Never refactor workers to use hexagonal services** without careful testing. The `app/config.py`, `app/auth.py`, and `app/db.py` files are backward-compat shims re-exporting from `app/core/`.

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

- **Domain layer** = pure Python `dataclasses` + ABC ports only (zero framework imports).
- **Config** = module-level constants (not Pydantic Settings). `load_dotenv()` called at import time in `app/core/config.py`.
- **No `utils.py` / `helpers.py`** — FFmpeg work in `FFmpegAdapter`, filesystem work in `FilesystemAdapter`.

## Engine Routing

`app/engine_router.py` dispatches by `normalize_language(lang)`:
- `"th"` → Typhoon ASR (Thai-only, NeMo FastConformer-Transducer 114M, ~1GB VRAM at FP16)
- `"en"` → Whisper (English, faster-whisper `large-v3-turbo`, ~3.5GB VRAM)
- `"auto"` → Whisper (auto-detect language, handles Thai-English mixed)
- Raises `ValueError` for anything else. Defaults to `"th"` if `None`/empty.

Chunk durations differ: Typhoon target=45s/max=90s, Whisper target=25s/max=30s.

## Workers

**Both transcription and compression jobs run as isolated subprocesses** to prevent VRAM leak in the main process:

```
# Transcription: spawned by transcription_router.py
sys.executable -m app.run_job <job_id> <path> <lang>

# Compression: spawned by main.py compress_queue_dispatcher background task (polls SQLite every 1s)
sys.executable -m app.run_compress_job <job_id> <input_path> <width> <bitrate> <crf> <preset> <encoder> <trim_start> <trim_end> <audio_extract_format>
```

- Workers **must lazy-import PyTorch/NeMo/faster-whisper** (at function level, not module top level).
- The `POST /v1/media/compress/jobs` endpoint only **creates a DB record**; the `compress_queue_dispatcher` in `main.py` actually spawns the process.
- Watchdog every 30s checks `_active_workers` dict for crashed processes; marks jobs failed.
- `app/modules/transcription/adapters/inbound/workers/run_job.py` and `app/modules/compression/adapters/inbound/workers/run_compress_job.py` are the actual subprocess entrypoints. The `app/run_job.py` / `app/run_compress_job.py` shims delegate to them.

## DI Pattern

FastAPI routers wire dependencies via factory functions — **no DI container**:
- `transcription_router.py` and `compression_router.py`: call `svc = get_*_service()` directly inside endpoint handlers (NOT via `Depends`).
- `settings_router.py`: uses `Depends(get_settings_service)` (the only one; inconsistent but intentional).
- Engine/media ports are `None` in API endpoints (used only in worker subprocesses).

## Test Architecture & Gaps

- `unittest` (stdlib) — no pytest, no mocking library.
- One test file per module under `tests/unit/<module>/`. Inline `Fake*Repository` classes implement domain ABCs (dict-backed).
- **Arrange-Act-Assert** with constructor injection of fake repos. No `setUp`/`tearDown`, no async tests.
- **Gaps**: No tests for: routers (no TestClient), workers, engines, or real repository implementations. `test_compression_router.py` only tests the `_is_safe_job_path()` helper.

## CUDA Resilience

- Transient errors: backoff + `clear_cuda_cache()` + retry (3 attempts, 5s backoff).
- Allocator corruption: `cudaDeviceReset` + model reload (via `engine_router.cuda_device_reset_all()`).
- `CUDA_RESET_BETWEEN_CHUNKS=true` resets CUDA context between long-form chunks (~6s cost per reset but prevents allocator corruption).
- **`torch.cuda.empty_cache()` must NOT be called between consecutive NeMo `transcribe()` calls** — triggers CUDA illegal memory access. Use `engine.clear_cuda_cache()` instead.

## State Machine

Job status transitions enforced in `app/db.py`:
```
queued → processing → completed | failed | cancelled  (terminal states are dead ends)
```
Retention policy: **completed** job DB records kept forever (only on-disk files cleaned up); **non-completed** records deleted after retention window.

## VRAM Mode

- `always` (default): models stay in VRAM once loaded.
- `idle`: unloaded after `MODEL_IDLE_TIMEOUT_SEC` (default 900s) of inactivity.
- Mode stored in SQLite `settings` table (seeded from env on first boot; editable at runtime via dashboard or `PUT /v1/settings/model`).

## Auth

- `x-api-key` header, HMAC constant-time comparison via `Depends(verify_api_key)` on all v1 REST routes.
- Web UI (`/`, `/audio/transcribe`, etc.) and WebSocket = no auth. Healthcheck `GET /healthz` = no auth.

## Key Files

- `requirements.txt` — GPU deps (CUDA 12.1 PyTorch index via `--extra-index-url`)
- `requirements-cpu.txt` — CPU deps (no CUDA index)
- `.env.example` → copy to `.env`
- `model/typhoon-asr-realtime.nemo` — weights (gitignored, auto-downloaded at Docker build time)
- `app/core/config.py` — all env vars defined here
- `app/core/db.py` — SQLite WAL connection factory (`timeout=30`, `busy_timeout=30000`, `row_factory=sqlite3.Row`)
- `app/db.py` — monolithic 799-line legacy with ALL SQLite CRUD (still in active use by workers and main.py bg tasks)
- `knowledges/realtime-streaming-architecture.md` — deep-dive on WebSocket flow

## Gitignored

`.env`, `.cache/`, `data/choonova-transcribe.db`, `data/jobs/`, `*.nemo`, `.agents/skills/`, `.serena/`, `skills-lock.json`

## Refs

- `.agents/skills/modular-hexagonal-architecture/SKILL.md` — enforces layer boundaries, dependency rules, anti-patterns
- `.agents/skills/project-onboarding/SKILL.md` — setup & first-run guide