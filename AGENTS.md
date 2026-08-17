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
│   ├── compression/       # Video compress: same structure
│   └── apitest/           # Endpoint self-test (/test): runner + in-memory run registry
├── api/v1/                # FastAPI routers: transcription_router, compression_router, settings_router, realtime_router, apitest_router
└── api/web/               # Jinja2 dashboard (views_router.py)
```

- **Domain layer** = pure Python `dataclasses` + ABC ports only (zero framework imports).
- **Config** = module-level constants (not Pydantic Settings). `load_dotenv()` called at import time in `app/core/config.py`.
- **No `utils.py` / `helpers.py`** — FFmpeg work in `FFmpegAdapter`, filesystem work in `FilesystemAdapter`.

## Engine Routing

`app/engine_router.py` dispatches by `normalize_language(lang)`:
- `"th"` → **Thai-tuned Whisper** (faster-whisper CT2, `Avocaduu14/whisper-th-large-v3-ct2`, int8_float16; local copy at `models/whisper-th-large-v3-ct2/` preferred via `whisper_thai_engine.resolve_thai_model_name()`, fallback to HF)
- `"en"` → Whisper (English, faster-whisper `large-v3-turbo`, ~3.5GB VRAM)
- `"auto"` → Whisper (auto-detect language, handles Thai-English mixed)
- Raises `ValueError` for anything else. Defaults to `"th"` if `None`/empty.

**Diambiguation:** For Thai + diarization the dropdown offers 3 models: `thai-whisper` (custom PyAnnote + `group_words_by_turns` path), `whisperx-thai` (WhisperX pipeline with the Thai-tuned CT2 ASR — accurate Thai text + forced-alignment word timestamps), and `whisperx` (WhisperX pipeline with the generic `large-v3-turbo` ASR). `whisperx-thai` is selected by `_select_asr_model()` in `app/whisperx_engine.py` (falls back to `resolve_thai_model_name()` local copy + `WHISPER_THAI_COMPUTE_TYPE`); the WhisperX singleton reloads its ASR model when the selection changes between turbo and Thai-tuned. Measured on `test_2_speaker.mp3` (char-level vs Gemini ref): thai-whisper+cap CER 15.7% / speaker agreement 95.2%, whisperx-thai CER 18.2% / 91.2% — **thai-whisper wins on both** (its 25-30s chunks beat WhisperX's VAD chunking for Thai text, and our PyAnnote path splits the opening speakers correctly while WhisperX's assignment merged 0-29.8s into one cluster); whisperx-thai's only edge is clean forced-alignment word timestamps with no `ถูกลง`-style residual.

Chunk durations differ: Thai Whisper target=25s/max=30s, English Whisper target=25s/max=30s. Engine singleton: `app/whisper_thai_engine.py` (lazy-imports faster-whisper). `WHISPER_THAI_MODEL` / `WHISPER_THAI_COMPUTE_TYPE` env vars in `app/core/config.py`. `scripts/download_models.py --whisper-thai` pre-downloads (also a Dockerfile build step).

## Speaker Diarization (Thai Path 3)

- **PyAnnote is the source of truth for who speaks when** — it runs on the full 16kHz WAV and labels turns correctly. Thai-tuned Whisper (`app/whisper_thai_engine.py`) emits **real word-level timestamps** (faster-whisper), so speaker attribution is no longer proportional-synthetic.
- **Turn consolidation is required before word bucketing.** Raw PyAnnote turns are fragmented (232 turns on `test_3_talk.mp3`) and contain cross-speaker time overlaps. `app/pyannote_engine.py:consolidate_diarization_turns()` resolves overlaps (longer turn dominates, later turn truncated), merges same-speaker gaps ≤0.6s, drops turns <0.5s → ~98 clean turns. `group_words_by_turns()` then buckets each word into the max-overlap turn.
- **`group_words_by_turns()` is word-level max-overlap bucketing with two guards for the measured misalignment source** (faster-whisper Thai word timestamps run late — utterance-tail words measured +1s to +4s late, their *ends* stretch over the VAD-kept silence and push later words late; PyAnnote turns start late / end early): (1) `cap_word_durations()` (`max_word_duration=1.2`) clips a stretched word's `end` to `start + 1.2s` before any bucketing — this alone fixes e.g. "วันนี้" (3.32s→8.08s) bleeding into the next turn; (2) a nearest-turn fallback (`gap_tolerance_sec=1.5`) recovers words landing in the pause gap between turns instead of dropping them silently; (3) segment `start`/`end` come from the bucketed words' real (capped) bounds so displayed times always match the text. **Do NOT reintroduce a segment-anchored variant** — real ASR segments span 20-30s across multiple speaker turns, and bucketing by the source segment's span mis-assigns whole chunks (measured 88.4% vs 95.2% speaker agreement on `test_2_speaker.mp3`). A word whose *start* itself is stamped late across a speaker boundary (e.g. "ถูกลง" 11.0s, spoken ~9.5s) remains a known residual — no timestamp-based rule fixes it without risky cross-turn pulls. All mechanisms are pure-python and unit-tested; `reconstruct_thai_words` threads the source ASR segment id under `seg` for diagnostics/contiguity.
- Thai path uses `group_words_by_turns` (turn-based grouping, ~89 segments on the test file) instead of the older `merge_speaker_overlap` + `group_speaker_segments` word-run approach — the older approach produced per-character speaker flapping (faster-whisper Thai tokens are character-level) and floods of UNKNOWN.
- **PyAnnote is the measured accuracy ceiling (~46% speaker agreement vs the Gemini reference, best-permutation over 0.1s samples);** no post-processing improves speaker identity, only output shape/granularity.
- **Typhoon ASR still exists** for the non-diarization inline/`en` paths via `app/asr_engine.py`; Thai + diarization now routes to Thai Whisper.
- Merge pipeline in `app/pyannote_engine.py`: `merge_speaker_overlap` (max-overlap + nearest-turn fallback, `gap_tolerance_sec=0.3`) → `smooth_speaker_labels` (absorbs `UNKNOWN` + snaps <1.5s blips sandwiched by the same speaker) → `group_speaker_segments`. Called from `transcription_router.py` (`/v1/audio/transcribe`) for the non-Thai word-level path and `job_worker.py` Path 3.
- `PyAnnoteDiarizer.diarize()` calls `relabel_speakers_chronological()` so `SPEAKER_00` is **always the first speaker in time** (PyAnnote cluster IDs are arbitrary).
- With diarization enabled, `/v1/audio/transcribe` returns `text` grouped as `[SPEAKER_00]: ...` lines (was plain text).
- `pythainlp==5.0.4` added to `requirements.txt` / `requirements-cpu.txt`.

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

## API Endpoint Self-Test (/test)

The `/test` page exercises the real `/v1/audio/transcribe/jobs` endpoint across the available ASR models. Runs are **server-owned and polling-based** — a page refresh / browser disconnect never loses the run or its results.

- **3 suites** (all audio jobs, `assets/test-audio-th.wav`):
  - `word-diar` — word-level + speaker (thai-whisper, whisperx)
  - `word-only` — word-level only (thai-whisper, whisper)
  - `no-word` — no word-level / no speaker (typhoon, thai-whisper, whisper)
- **`POST /v1/tests/run`** returns **202 + run_id** immediately and starts a detached background task (`asyncio.create_task`); the run is NOT tied to the HTTP request. **409** if a run is active (body carries `active_run_id` + `active_suite`). Only one run at a time.
- **State lives in an in-memory `RunRegistry`** (`app/modules/apitest/application/run_registry.py`, capped at 5 runs, oldest evicted). In-memory only — lost on server restart (fine; just re-run). Event-loop safe (single uvicorn process, no locks).
- **Persistent pass/fail (SQLite)**: per-suite and per-test-card pass/fail (no detailed results) are stored by `SQLiteSelfTestStatusRepository` (`adapters/outbound/sqlite_self_test_status_repository.py`, tables `self_test_status` / `self_test_suite_status` / `self_test_meta`). Suite cards show a ✅/❌/⚪ verification badge that survives a plain server restart. A **new build resets everything to "not tested"**: `application/build_stamp.py` compares a sha256 fingerprint of the deployed app source (stored in `self_test_meta`) at startup (`main.py` `startup_event`) and clears the statuses when it changed.
- **Polling endpoints** (all `x-api-key`): `GET /v1/tests/info` (assets + defaults + persisted suite/test status), `GET /v1/tests/runs` (history), `GET /v1/tests/runs/active`, `GET /v1/tests/runs/{id}` (live or finished snapshot).
- **Frontend** (`app/static/js/apitest.js`, `app/templates/apitest.html`): polls `/runs/{id}` every ~5s, reconnects to any active run on page load / window focus, renders a recent-runs bar (5) to re-open past results, and shows a "เคยผ่านการตรวจสอบแล้ว" tag on result cards that passed in a previous run.
- **Module structure**: `domain/` (entities `EndpointTest`/`ApiTestReport`/`FieldCheck`, `ApiHttpPort`) → `application/` (`apitest_runner.py` orchestrator, `run_registry.py`) → `adapters/outbound/self_http_client.py` (httpx against `http://127.0.0.1:{PORT}`). Runner callbacks (`on_test`/`on_progress`/`on_start`) are **async** and mutate the run registry.

## Test Architecture & Gaps

- `unittest` (stdlib) — no pytest, no mocking library.
- One test file per module under `tests/unit/<module>/`. Inline `Fake*Repository`/`FakeApiHttp` classes implement domain ABCs (dict-backed).
- **Arrange-Act-Assert** with constructor injection of fake repos. `apitest` tests use `asyncio.run` for the async runner/registry (some use `setUp`/`tearDown` temp dirs).
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
- `models/typhoon-asr-realtime.nemo` — weights (gitignored, auto-downloaded at Docker build time)
- `app/core/config.py` — all env vars defined here
- `app/core/db.py` — SQLite WAL connection factory (`timeout=30`, `busy_timeout=30000`, `row_factory=sqlite3.Row`)
- `app/db.py` — monolithic 799-line legacy with ALL SQLite CRUD (still in active use by workers and main.py bg tasks)
- `knowledges/realtime-streaming-architecture.md` — deep-dive on WebSocket flow

## Gitignored

`.env`, `.cache/`, `data/choonova-transcribe.db`, `data/jobs/`, `*.nemo`, `.agents/skills/`, `.serena/`, `skills-lock.json`

## Refs

- `.agents/skills/modular-hexagonal-architecture/SKILL.md` — enforces layer boundaries, dependency rules, anti-patterns
- `.agents/skills/project-onboarding/SKILL.md` — setup & first-run guide