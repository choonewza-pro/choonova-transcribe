# ChooNova Transcribe

<p align="center">
  <img src="app/static/choonova-transcribe-cover.png" alt="ChooNova Transcribe Cover" width="100%" style="max-width: 900px; border-radius: 12px;">
</p>

Thai Speech-to-Text API and video processing service powered by Thai-tuned Whisper, Typhoon ASR Realtime & Faster Whisper (`large-v3-turbo`), with speaker diarization and FFmpeg video compression.

> 💡 **For Developers & AI Agents:** See [project-onboarding SKILL.md](file://.agents/skills/project-onboarding/SKILL.md) for setup and [knowledges/](file://knowledges/) for deep-dive technical architecture documents.

## Overview

ChooNova Transcribe is a high-performance audio transcription and media processing API. It provides accurate Thai speech-to-text through a stack of three ASR engines — **Thai-tuned Whisper** (`thai-whisper`, the default for Thai), **Typhoon ASR Realtime** (NeMo FastConformer-Transducer 114M), and **Faster Whisper** (`large-v3-turbo`, for English/Auto-detect) — plus **PyAnnote 3.1** speaker diarization and a **WhisperX** alignment pipeline. The service supports REST APIs for batch processing, WebSockets for real-time streaming, and a built-in FFmpeg video compressor. It runs on NVIDIA GPUs (CUDA 12.1) and CPUs, and a missing `HF_TOKEN` simply disables diarization so CPU-only / offline installs stay fully usable.

## Key Features

- **Thai-first Multi-Engine ASR**: Thai defaults to **Thai-tuned faster-whisper** (`Avocaduu14/whisper-th-large-v3-ct2`, ~2-3GB VRAM) for the most accurate Thai text and real word timestamps; `typhoon` (NeMo FastConformer-Transducer 114M, ~1GB VRAM) is the fastest Thai engine, especially on CPU; `whisper` covers English and Thai-English mixed content.
- **OpenAI-Compatible Audio API**: Full drop-in replacement for OpenAI Whisper API (`/v1/audio/transcriptions`, `/v1/models`). Seamlessly integrates with official OpenAI Python/Node SDKs, Open WebUI, Obsidian, and third-party clients. Supports output formats: `json`, `text`, `srt`, `vtt`, and `verbose_json` (with `timestamp_granularities[]`).
- **Real-time Transcription**: High-performance WebSocket endpoint (`/v1/realtime/stream`) for zero-disk-write live microphone transcription with in-memory FFmpeg pipes, 600ms streaming updates, and sliding window preview (Thai only).
- **Short Audio Transcription**: REST API for quick, synchronous processing of short multipart audio uploads.
- **Long-form Media Pipeline**: Asynchronous processing for large video/audio files (up to 1GB+, configurable) with silence-aware chunking and automatic cleanup.
- **Speaker Diarization with Speaker Count Controls**: Multi-speaker identification and labeling (`[SPEAKER_00]`, `[SPEAKER_01]`, ...) powered by PyAnnote 3.1. Three model choices for Thai: `thai-whisper` (PyAnnote + word-level turn bucketing — most accurate Thai, best speaker agreement), `whisperx-thai` (WhisperX pipeline with the Thai-tuned CT2 ASR + forced alignment), and `whisperx` (generic `large-v3-turbo` WhisperX). Supports explicit speaker count controls (`num_speakers`, `min_speakers`, `max_speakers`) to lock clustering. A master switch (`DIARIZATION_ENABLED`) auto-disables when `HF_TOKEN` is missing — enforced across the API, workers, web UI, and self-test.
- **Video Compression**: Asynchronous FFmpeg-based video compressor with queue management, supporting both CPU (libx264) and GPU (NVENC) encoding, resize, trim, and audio extraction.
- **Job History & Management**: Built-in SQLite tracking for transcription and compression jobs with a web-based dashboard and export capabilities (.txt, .srt, .json).
- **Dynamic VRAM Management**: Configurable model residency (Always-on vs. Idle timeout) to optimize GPU memory usage.

## Architecture

ChooNova Transcribe follows a Pragmatic Modular Monolith + Hexagonal Architecture:

- **API Delivery**: FastAPI routers (`app/api/v1/`) use clean Hexagonal Architecture patterns, decoupling delivery from domain logic via service factories.
- **Isolated Workers & Background Tasks (Legacy/Monolithic Hybrid)**: Long-running jobs (transcription and compression) and background watchdogs run as isolated subprocesses ([`job_worker.py`](file:///D:/_PROJECT_/choonova-transcribe/app/job_worker.py), [`compress_worker.py`](file:///D:/_PROJECT_/choonova-transcribe/app/compress_worker.py)) using monolithic connections ([`app/db.py`](file:///D:/_PROJECT_/choonova-transcribe/app/db.py)).
- **CUDA Resilience**: Implements transient error retries (with backoff) and allocator corruption recovery via `cudaDeviceReset`.

### Model Selection Matrix

Models are validated against a `(language × enable_diarization)` matrix (see `app/model_selection.py`):

| Model          | Language     | Diarization | Engine & Pipeline                                                                                          |
| -------------- | ------------ | ----------- | ---------------------------------------------------------------------------------------------------------- |
| `thai-whisper` | `th`         | ✅ or ❌    | **Thai-tuned faster-whisper CT2** (`WHISPER_THAI_MODEL`) — default Thai engine; real word timestamps (reconstructed via PyThaiNLP `newmm`). |
| `typhoon`      | `th`         | ❌          | **NeMo Typhoon ASR Realtime** (FastConformer-Transducer 114M, ~1GB VRAM) — fastest Thai option, especially on CPU. |
| `whisper`      | `th`, `en`, `auto` | ❌  | **Faster Whisper** `large-v3-turbo` (CTranslate2, ~3.5GB VRAM) — English and auto language detection.        |
| `whisperx`     | `en`, `auto` (and `th`) | ✅ | **WhisperX** pipeline: transcribe → phoneme forced alignment (wav2vec2) → PyAnnote 3.1 → word speaker assignment. |
| `whisperx-thai`| `th`         | ✅          | **WhisperX** pipeline with the **Thai-tuned CT2 ASR** (`WHISPER_THAI_MODEL`) — accurate Thai text + forced-alignment word timestamps. |

Runtime routing (`app/engine_router.py`): explicit `model=` wins; otherwise `th` → `thai-whisper`, `en`/`auto` → `whisper`.

Processing pipelines:

- **Thai (no diarization)**: silence-aware chunking (defaults `45s` target / `90s` max) → Thai Whisper → word timestamps reconstructed with PyThaiNLP.
- **Thai + diarization**: Thai Whisper chunks → PyAnnote 3.1 diarization on the full 16kHz WAV → turn consolidation → word-level max-overlap bucketing into speaker turns (`group_words_by_turns`). Measured to give the best Thai accuracy and speaker agreement on this codebase.
- **English/Auto (no diarization)**: silence-aware chunking (defaults `25s` target / `30s` max) → Faster Whisper.
- **English/Auto + diarization**: WhisperX full pipeline (transcribe → forced alignment → PyAnnote 3.1 → word speaker assignment).

### Dual-Architecture Rationale (Mid-Migration)

We intentionally maintain a hybrid architectural state where the API delivery layer is fully hexagonal, while worker subprocesses and background tasks utilize monolithic handlers. This design choice is driven by:

1. **VRAM/RAM Containment**: Worker subprocesses require strict lazy loading of heavy deep learning packages (`PyTorch`/`NeMo`/`faster-whisper`/`PyAnnote`/`WhisperX`). Keeping workers as lightweight monolithic CLI scripts prevents accidental package imports from polluting the main API process memory.
2. **SQLite WAL Concurrency**: Subprocesses access the database concurrently with the FastAPI process. The monolithic database wrapper ([`app/db.py`](file:///D:/_PROJECT_/choonova-transcribe/app/db.py)) is production-hardened for SQLite concurrent write locks under WAL mode.
3. **Pragmatic Complexity (Low ROI)**: Workers are simple linear CLI scripts (e.g., FFmpeg extraction -> Model Inference -> DB Update). Introducing interface port abstractions here would add boilerplates without real-world utility.

## Technology Stack

| Layer         | Technology                            | Purpose                                              |
| ------------- | ------------------------------------- | ---------------------------------------------------- |
| Language      | Python 3.12                           | Core application logic                               |
| Web Framework | FastAPI + Uvicorn                     | High-performance async HTTP/WebSocket server         |
| Deep Learning | PyTorch 2.5.1                         | Tensor operations and model execution (CUDA 12.1)    |
| ASR Models    | NeMo Toolkit 2.1, faster-whisper 1.1  | Typhoon ASR (114M), Thai-tuned Whisper (`whisper-th-large-v3-ct2`), Whisper (`large-v3-turbo`) |
| Diarization   | PyAnnote.audio 3.x (pipeline `pyannote/speaker-diarization-3.1`) & WhisperX 3.3.2 | Multi-speaker identification and word alignment |
| Thai NLP      | PyThaiNLP 5.0.4                       | Thai word tokenization / reconstruction (`newmm`)    |
| Audio/Video   | FFmpeg, librosa, soundfile            | Media extraction, silence detection, and compression |
| Storage       | SQLite (WAL mode)                     | Transactional job history and settings persistence   |

## Requirements

**Required:**

- Docker and Docker Compose (recommended deployment) **or** Python 3.12 + the dependency files (see [Development](#development))
- Minimum 5GB Free Disk Space (`MIN_FREE_DISK_GB`)

**Recommended (GPU):**

- NVIDIA GPU with at least 12GB VRAM (tested on RTX 4080 Laptop GPU)
- NVIDIA Container Toolkit (for Docker deployments)
- CUDA 12.1 (for local development)

**Supported (CPU Fallback):**

- Windows, Mac M1–M4, or Linux CPUs — works out of the box; Thai diarization is auto-disabled unless `HF_TOKEN` is configured or local PyAnnote models are present in `models/`

## Quick Start

### Step by Step

1. **Install Docker Desktop** (for Windows, see instructions and download at [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/))
2. **Copy `.env.example` to `.env`**
   ```bash
   cp .env.example .env
   ```
3. **Edit the variables in `.env`**
   - Change `GATEWAY_API_KEY` from `change-me-in-production` to the auth key you want to use
   - Set the `DEVICE` variable:
     - If running on **CPU**, change it to `DEVICE=cpu`
     - If running on an **NVIDIA GPU**, change it to `DEVICE=cuda`
   - **Diarization (optional):** `DIARIZATION_ENABLED` is blank by default, which means diarization is **auto-enabled only when `HF_TOKEN` is set** (PyAnnote/WhisperX gated models). Leave it blank for a clean CPU/no-token install.
   - **Set queue and concurrency limits (Important Queue Limits):**
     ```env
     # Controls the transcription queue
     TRANSCRIBE_MAX_CONCURRENT=1
     TRANSCRIBE_MAX_QUEUED=10

     # Controls the video compression queue
     COMPRESS_MAX_CONCURRENT=1
     COMPRESS_MAX_QUEUED=10
     ```
4. **Install and run on a Docker Container**
   - For **Windows / Mac** running on **CPU**:
     ```bash
     docker compose -f docker-compose-cpu.yml up -d --build
     ```
   - For **Windows** with an **NVIDIA GPU**:
     ```bash
     docker compose up -d --build
     ```
   - To integrate with the `km4u-network` external network (other services):
     ```bash
     docker network create km4u-network   # once, if not already created
     docker compose -f docker-compose-km4u.yml up -d --build
     ```
5. **Open the app** at [http://localhost:8830](http://localhost:8830)
6. **Verify the service is working (after installation)**
   - Go to the **API Self-Test** page: [http://localhost:8830/test](http://localhost:8830/test)
   - The page is only accessible once you have set an API Key (enter it on `/setting` or use `http://localhost:8830/test?api_key=YOUR_KEY`)
   - Choose one of the **4 suites** — **Word-level + ผู้พูด**, **Word-level เท่านั้น**, **ไม่มี Word-level**, or **Sync /v1/audio/transcribe** — and press **▶ Start Automated Test**. The service sends `assets/test-audio-th.wav` to `/v1/audio/transcribe/jobs` (and the sync endpoint) across the available ASR models (Thai Whisper / WhisperX / Whisper / Typhoon) and reports pass/fail per test with an `X/N` progress bar
   - The **Word-level + ผู้พูด** suite requires speaker diarization to be enabled (it is disabled/blocked when `DIARIZATION_ENABLED` is off — e.g. no `HF_TOKEN`); the **Sync** suite simply skips its diarization card in that case
   - Runs are **server-owned and polling-based** (status refreshed every 5s): refresh or disconnect the page and it automatically reconnects to the live run; only one run runs at a time (the start button is disabled while a run is active). The **recent-runs bar** (last 5) lets you re-open past results
   - Each suite card shows a **persistent verification badge** (✅ ผ่านการตรวจสอบแล้ว / ❌ ยังไม่ผ่าน / ⚪ ยังไม่ได้ทดสอบ) stored in SQLite — it survives a plain server restart, and is automatically reset to ⚪ when a **new build** is deployed (the deployed app source is fingerprinted at startup, so the status survives `./data:/app/data` mounts but not new code)
   - Job transcription can take minutes (model load + GPU/CPU inference) — the progress bar keeps you informed while the run is active

## Configuration

Application behavior is controlled via environment variables. Copy `.env.example` to `.env` to configure the service. Defaults below are the **code defaults** — `.env.example` may ship different values (e.g. `MODEL_LOAD_MODE=idle`, `MAX_UPLOAD_SIZE_MB=10240`).

### Service & Security

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `GATEWAY_API_KEY`            | `change-me-in-production` | Yes      | Secret key for API authentication.                                          |
| `HOST` / `PORT`              | `0.0.0.0` / `8830`        | No       | Bind address and port.                                                      |
| `LOG_LEVEL`                  | `info`                    | No       | Log verbosity.                                                              |
| `ALLOW_ACCESS_TRANSCRIBE_HISTORY` | `false`              | No       | Bypasses API key authentication on ASR history. **⚠️ SECURITY RISK**: Enabling this allows public access to transcripts and media files. |
| `ALLOW_ACCESS_COMPRESS_HISTORY` | `false`                | No       | Bypasses API key authentication on compress history. **⚠️ SECURITY RISK**: Enabling this allows public access to compression logs and videos. |

### Storage & Hardware

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `DATA_DIR`                   | `./data`                  | No       | Directory for the SQLite database.                                          |
| `TEMP_JOBS_DIR`              | `/tmp/choonova-transcribe-jobs` | No | Directory for temporary media & job files.                                  |
| `MIN_FREE_DISK_GB`           | `5.0`                     | No       | Minimum required free disk space in GB before rejecting new jobs.           |
| `DEVICE`                     | `cuda`                    | No       | Target device (`cuda` or `cpu`). Auto-detects if CUDA is missing.           |
| `CUDA_RETRY_ATTEMPTS` / `CUDA_RETRY_BACKOFF_SEC` | `3` / `5` | No | Transient CUDA error retries with backoff.                       |
| `CUDA_RESET_ON_ALLOCATOR_ERROR` / `CUDA_RESET_BETWEEN_CHUNKS` | `false` / `true` | No | Allocator-corruption recovery (`cudaDeviceReset`) and per-chunk resets. |

### ASR Models & VRAM

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `MODEL_PATH`                 | `models/typhoon-asr-realtime.nemo` | No | Path to the Typhoon ASR Realtime NeMo weights (auto-downloaded at Docker build). |
| `WHISPER_MODEL`              | `deepdml/faster-whisper-large-v3-turbo-ct2` | No | faster-whisper model. Systran removed `faster-whisper-large-v3-turbo`, so the default is the community CT2 mirror; legacy bare `large-v3-turbo` still resolves at runtime. |
| `WHISPERX_MODEL`             | `large-v3-turbo`          | No       | WhisperX ASR model for English/Auto + diarization and the plain `whisperx` selection. `whisperx.load_model()` passes the name straight to faster-whisper, so a faster-whisper CT2 repo id or a plain Whisper size name both work. |
| `WHISPER_THAI_MODEL`         | `Avocaduu14/whisper-th-large-v3-ct2` | No | Thai-tuned faster-whisper (CT2) for the Thai offline path — more accurate than Typhoon + real word timestamps for diarization. Alternatives: `mort666/whisper-large-v3-th-f16-faster` (~6GB VRAM, higher accuracy). A local copy in `models/` is preferred (`resolve_thai_model_name()`), falling back to HF. |
| `WHISPER_THAI_COMPUTE_TYPE`  | `int8_float16` (GPU) / `int8` (CPU) | No | Compute type for the Thai Whisper CT2 model. |
| `HF_TOKEN`                   | *(Empty)*                 | No       | Hugging Face Hub token. Required for PyAnnote 3.1 & WhisperX gated models (`pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`). |
| `MODEL_LOAD_MODE`            | `always`                  | No       | VRAM residency seed: `always` or `idle`.                                    |
| `MODEL_IDLE_TIMEOUT_SEC`     | `900`                     | No       | Seconds of inactivity before unloading models (if `idle`).                  |

### Speaker Diarization

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `DIARIZATION_ENABLED`        | *(blank = auto)*          | No       | Master toggle for speaker diarization. **Blank/empty = auto-off unless `HF_TOKEN` is set** (so CPU/no-token installs stay fully usable). Set explicitly to `true` to force-enable (even without `HF_TOKEN`), `false` to force-disable. |
| `DIARIZATION_MODEL`          | `pyannote/speaker-diarization-3.1` | No | Hugging Face model ID for PyAnnote diarization pipeline.                     |
| `DIARIZATION_MIN_SPEAKERS`   | *(Empty)*                 | No       | Optional hint for minimum expected speakers (auto-detect if empty).          |
| `DIARIZATION_MAX_SPEAKERS`   | *(Empty)*                 | No       | Optional hint for maximum expected speakers (auto-detect if empty).          |

### Transcription Pipeline

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `TRANSCRIBE_MAX_CONCURRENT`  | `1`                       | No       | Maximum concurrent transcription jobs.                                      |
| `TRANSCRIBE_MAX_QUEUED`      | `10`                      | No       | Maximum jobs waiting in transcription queue before returning 429.          |
| `TRANSCRIBE_RETENTION_HOURS` | `24`                      | No       | Hours to retain transcription media files on disk.                          |
| `TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC` | `45.0` | No | Target chunk size for Thai silence-based splitting. |
| `TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC` | `90.0` | No | Max chunk size for Thai silence-based splitting. |
| `TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC` | `25.0` | No | Target chunk size for English/Auto silence-based splitting. |
| `TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC` | `30.0` | No | Max chunk size for English/Auto silence-based splitting. |

### Video Compressor

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `COMPRESS_ENCODER`           | `libx264`                 | No       | Video encoder: `libx264` or `nvenc` (auto-falls back if NVENC unavailable). |
| `COMPRESS_PRESET`            | `medium`                  | No       | x264 preset (`ultrafast`..`veryslow`).                                      |
| `COMPRESS_CRF`               | `28`                      | No       | CRF quality (18-32, higher = smaller).                                      |
| `COMPRESS_MAX_CONCURRENT`    | `1`                       | No       | Maximum concurrent compression jobs.                                        |
| `COMPRESS_MAX_QUEUED`        | `10`                      | No       | Maximum jobs waiting in compression queue.                                  |
| `COMPRESS_RETENTION_HOURS`   | `24`                      | No       | Hours to retain compressed output files on disk.                            |

### Upload Guardrails & Self-Test

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `MAX_UPLOAD_SIZE_MB`         | `0` (unlimited)           | No       | Size limit for async long-form jobs (`0` = unlimited; `.env.example` ships `10240` = 10GB). |
| `MAX_AUDIO_UPLOAD_SIZE_MB`   | `50.0`                    | No       | Size limit for synchronous audio endpoint.                                  |
| `MAX_MEDIA_DURATION_SEC`     | `21600.0`                 | No       | Max duration in seconds for uploaded media to prevent GPU hogging.          |
| `MAX_AUDIO_DURATION_SEC`     | `3600.0`                  | No       | Max duration in seconds for short audio endpoints (full-file single-pass).  |
| `APITEST_TRANSCRIBE_MAX_WAIT_SEC` | `1800`                | No       | Max wall-clock seconds waiting for an async job before the self-test is marked FAILED. |
| `APITEST_POLL_INTERVAL_SEC`  | `5`                       | No       | How often the self-test polls the job status endpoint.                      |

_(Note: Environment variables for VRAM mode only seed the database on first boot. The database is the source of truth thereafter.)_

## Authentication / Security

- **API Endpoints**: All `/v1` REST endpoints require an API key passed via either `Authorization: Bearer <GATEWAY_API_KEY>` (standard for OpenAI SDKs & Third-party clients) or `x-api-key: <GATEWAY_API_KEY>` (REST Gateway header). The system uses constant-time HMAC comparison to verify keys.
- **History Dashboards**: The transcription history (`/media/transcribe/jobs/history`) and compression history (`/media/compress/jobs/history`) pages are secured by API key checks. You can log in via query parameter (`?api_key=YOUR_KEY`), browser cookie, or via the manual login form on the Access Denied page. The session is seamlessly synchronized between browser cookies and `localStorage`.
- **Public Share Bypasses**: Bypasses can be enabled via `ALLOW_ACCESS_TRANSCRIBE_HISTORY=true` and `ALLOW_ACCESS_COMPRESS_HISTORY=true` to publicly share history dashboards. When active, a prominent security warning banner is displayed on the homepage and respective history dashboards to alert operators of the open access.
- **Web UI**: The landing page, short transcription forms, and microphone streaming page remain unauthenticated for ease of local access.
- **WebSockets**: The real-time streaming endpoint (`/v1/realtime/stream`) requires API key authentication via the `typhoon_asr_api_key` **cookie** (set automatically when you save your API key in the Settings page at `/setting`). The cookie is sent by the browser with the WebSocket upgrade request — no query parameter needed. If the cookie is missing or invalid, the server rejects the connection with close code `4001` before loading any ASR model.
- **Upload Validation (Defense-in-Depth)**: All file uploads undergo multi-layer inspection before processing:
  - Extension and Size verification.
  - Magic Bytes signature checking (`filetype`) to prevent file masking.
  - Deep container inspection via `ffprobe` to reject malicious Polyglot files.
  - Safe filename sanitization to prevent Path Traversal attacks.
- **Subprocess & FFmpeg Security**: FFmpeg executions run securely without `shell=True` and enforce `-protocol_whitelist file,pipe,crypto` to completely eliminate Server-Side Request Forgery (SSRF) risks from malicious media playlists (e.g., weaponized `.m3u8`).

## Usage

### Web UI

Navigate to `http://localhost:8830/` to access the built-in HTML dashboard where you can:

- Transcribe short audio directly (`/audio/transcribe`).
- Stream microphone audio in real-time (`/realtime/stream`).
- Upload long videos for asynchronous transcription and monitor progress (`/media/transcribe`).
- Compress videos (`/media/compress`).
- Adjust Model VRAM Settings (`/setting`).
- Run the automated API self-test (`/test`) to verify the audio transcription job endpoints work end-to-end.

### Model Selection (Thai)

For Thai audio, pass `model=` explicitly to pick an engine:

| Model          | Best for                                                        |
| -------------- | --------------------------------------------------------------- |
| `thai-whisper` | Default. Most accurate Thai text + word timestamps; diarization-capable. |
| `typhoon`      | Fastest Thai transcription — recommended on CPU (NeMo, no word timestamps). |
| `whisperx-thai`| Thai + diarization with WhisperX forced-alignment word timestamps. |
| `whisper`      | English / Thai-English mixed content.                           |

### Model VRAM Residency

The ASR models (Thai Whisper + Whisper + Typhoon) consume significant GPU memory (~1-4GB). Their lifecycle is managed in two modes:

- **`always`** (Default): Models remain in VRAM permanently once loaded. Best for low latency.
- **`idle`**: Models are unloaded after `MODEL_IDLE_TIMEOUT_SEC` of inactivity. The next request pays a cold-start cost (~10-60s) to reload.

You can toggle this mode at runtime without restarting the server via the web dashboard (`/setting`) or the `PUT /v1/settings/model` endpoint.

## API Reference

### REST Endpoints

| Method | Path                                             | Auth | Description                                        |
| ------ | ------------------------------------------------ | ---- | -------------------------------------------------- |
| GET    | `/healthz`                                       | ❌   | Health check with engine/model residency states.   |
| POST   | `/v1/audio/transcriptions`                       | ✅   | **OpenAI Drop-in**: Transcribe audio (JSON/SRT/VTT/verbose_json). |
| GET    | `/v1/models`                                     | ❌   | **OpenAI Drop-in**: List available models (`whisper-1`, `typhoon-asr`). |
| GET    | `/v1/models/{model_id}`                          | ❌   | **OpenAI Drop-in**: Retrieve model metadata.       |
| POST   | `/v1/audio/transcribe`                           | ✅   | Synchronously transcribe short audio (multipart).  |
| POST   | `/v1/audio/transcribe/jobs`                      | ✅   | Enqueue short audio transcription job (returns 202). |
| POST   | `/v1/media/transcribe/jobs`                      | ✅   | Enqueue long-form transcription job (returns 202). |
| GET    | `/v1/media/transcribe/jobs`                      | ✅   | List transcription jobs.                           |
| GET    | `/v1/media/transcribe/jobs/{id}`                 | ✅   | Check status and retrieve transcription results.   |
| DELETE | `/v1/media/transcribe/jobs/{id}`                 | ✅   | Delete job record and media files.                 |
| GET    | `/v1/media/transcribe/jobs/{id}/export/{format}` | ✅   | Export results as `txt`, `srt`, or `json`.         |
| POST   | `/v1/media/compress/jobs`                        | ✅   | Enqueue video compression job (returns 202).       |
| GET    | `/v1/media/compress/jobs`                        | ✅   | List compression jobs.                             |
| GET    | `/v1/media/compress/jobs/{id}`                   | ✅   | Check compression job status.                      |
| GET    | `/v1/media/compress/jobs/{id}/download`          | ✅   | Download the compressed MP4 output.                |
| GET    | `/v1/media/compress/jobs/{id}/audio`             | ✅   | Download the extracted audio stream.               |
| GET    | `/v1/media/compress/retention`                   | ✅   | Compression retention window summary.              |
| GET    | `/v1/settings/model`                             | ✅   | Read model VRAM mode + residency states.           |
| PUT    | `/v1/settings/model`                             | ✅   | Change model VRAM mode at runtime.                 |
| GET    | `/v1/tests/info`                                 | ✅   | Self-test assets, defaults, and persisted status.  |
| POST   | `/v1/tests/run`                                  | ✅   | Start an automated self-test run (returns 202).    |
| GET    | `/v1/tests/runs`                                 | ✅   | Self-test run history.                             |
| GET    | `/v1/tests/runs/active`                          | ✅   | Currently active self-test run (if any).           |
| GET    | `/v1/tests/runs/{run_id}`                        | ✅   | Live or finished self-test run snapshot.           |

### Usage Examples

#### 1. Official OpenAI Python SDK (Drop-in Replacement)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8830/v1",
    api_key="change-me-in-production"
)

# Transcribe audio to verbose JSON with word timestamps
with open("meeting.mp3", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
        timestamp_granularities=["word", "segment"]
    )
print(transcript.text)
```

#### 2. cURL Examples

**OpenAI-Compatible Transcription (SRT Subtitles)**

```bash
curl -X POST http://localhost:8830/v1/audio/transcriptions \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@sample.mp3" \
  -F "model=whisper-1" \
  -F "response_format=srt"
```

**Short Audio Transcription (Thai - Thai Whisper)**

```bash
curl -X POST http://localhost:8830/v1/audio/transcribe \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@audio.mp3" -F "language=th" -F "model=thai-whisper" -F "with_timestamps=true"
```

**Long-form Video Transcription with Exact Speaker Count (Thai Whisper + Diarization)**

```bash
curl -X POST http://localhost:8830/v1/media/transcribe/jobs \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@meeting.mp4" -F "language=th" -F "model=thai-whisper" \
  -F "enable_diarization=true" -F "num_speakers=2"
```

**Video Compression (Resize & Trim)**

```bash
curl -X POST http://localhost:8830/v1/media/compress/jobs \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@video.mp4" -F "target_width=1280" -F "bitrate_kbps=2000" \
  -F "start=00:01:00" -F "end=00:02:00"
```

### WebSocket Streaming

Authentication is handled automatically via the `typhoon_asr_api_key` cookie (set from the Settings page). The browser sends it with the WebSocket upgrade request — no extra step needed.

```javascript
const ws = new WebSocket(`ws://localhost:8830/v1/realtime/stream`);
// Send audio Blob and text commands: "INTERIM", "COMMIT_SEGMENT", "CLEAR"
ws.send(audioBlob);
ws.send("COMMIT_SEGMENT");
```

_(Note: Real-time websocket streaming supports Thai language only via Typhoon)_

## Processing Flow

### Long-form Transcription Pipeline

```
POST /v1/media/transcribe/jobs (multipart)
   │ (Returns 202 Accepted → id)
   ▼
run_job.py → job_worker.py (isolated subprocess)
   ├─ 1. FFmpeg extract → 16kHz mono 16-bit WAV
   ├─ 2. Silence-aware chunking (Thai: target 45s / max 90s; EN/Auto: target 25s / max 30s; 0.5s overlap on hard cuts)
   ├─ 3. GPU transcription loop (with global asyncio.Lock) — Thai Whisper for "th", Whisper for "en"/"auto"
   ├─ 4. Diarization (if enabled): th → PyAnnote 3.1 + word-level turn bucketing; en/auto → WhisperX pipeline
   ├─ 5. Build full text + timestamps + SRT
   └─ 6. Save results to SQLite & cleanup temp files
```

### Video Compressor Flow

```
POST /v1/media/compress/jobs (multipart)
   │ (Returns 202 Accepted → id + queue position)
   ▼
compress_queue_dispatcher (FIFO queue)
   ▼
run_compress_job.py (isolated subprocess)
   ├─ 1. ffprobe → extract metadata (resolution, duration, audio streams)
   ├─ 2. FFmpeg encode (scale, bitrate/CRF, preset, trim, libx264/nvenc)
   │      ↳ Auto-fallback to libx264 if NVENC fails at runtime.
   ├─ 3. Update SQLite with progress and final output paths.
   └─ 4. Delete input file immediately; retain output per schedule.
```

## Data Lifecycle

- **Creation**: Media is uploaded and temporarily saved to `TEMP_JOBS_DIR` (`/tmp/choonova-transcribe-jobs` inside the container).
- **Processing**: A worker subprocess processes the media.
- **Completion**: Extracted texts, SRTs, and timestamps are saved in the SQLite database (`choonova-transcribe.db`).
- **Retention**: Media files are kept on disk based on `TRANSCRIBE_RETENTION_HOURS` or `COMPRESS_RETENTION_HOURS` (default 24 hours).
- **Cleanup**: A background task automatically deletes old media files to save disk space. The database records are kept indefinitely unless manually deleted via `DELETE /v1/media/transcribe/jobs/{id}`. Container restart will not wipe the database if the `./data` volume is mounted.

## Development

Local development setup requires manually installing dependencies:

```bash
# Requires Python 3.12 (see .python-version) — GPU torch has no wheel for other versions.

# GPU environment
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU environment
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
```

Pre-download ASR weights (optional, recommended before first run):

```bash
python scripts/download_models.py --whisper-thai
```

Verify the compute device after install:

```bash
# Must print True + your Nvidia GPU name on a GPU machine; False on CPU machines.
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

## Testing

The project uses the standard `unittest` library with fake in-memory repositories (no mocking framework) to test domain logic in isolation.

```bash
python -m unittest discover -s tests/unit -t . -v
```

Syntax check:

```bash
python -m py_compile app/main.py
```

## Project Structure

```
app/
├── main.py          # FastAPI application entry point
├── *worker.py       # Isolated subprocess workers (Transcription, Compression)
├── run_job.py       # Subprocess entry shims (→ modules/.../workers/)
├── core/            # Cross-cutting concerns (config, db, security)
├── modules/         # Domain bounded contexts (settings, transcription, compression, apitest)
├── api/             # Delivery layer
│   ├── v1/          # REST & WebSocket API routers
│   └── web/         # HTML Dashboard view routers
├── templates/       # Jinja2 HTML templates
└── static/          # Vanilla CSS & JS assets
knowledges/          # 📚 Technical knowledge base & architecture deep-dives for study/reference
scripts/             # Model download & diagnostic utilities
tests/
└── unit/            # Unit tests using in-memory Fake adapters
```

## Deployment / Operations

- **Container Deployment**: Docker Compose is the recommended deployment strategy. Three compose files are provided: `docker-compose.yml` (GPU), `docker-compose-cpu.yml` (CPU), and `docker-compose-km4u.yml` (GPU on the `km4u-network` external network — create it first with `docker network create km4u-network`, or remove the external network constraint for standalone use).
- **Model Weights**: The Docker build downloads the NeMo Typhoon weights (`models/typhoon-asr-realtime.nemo`) and pre-downloads the Thai Whisper CT2 model (see `scripts/download_models.py`).
- **Persistent Storage**: Ensure you mount `./data:/app/data` to persist job histories and application settings across restarts.
- **Observability**: Uvicorn access logs and application logs are outputted to `stdout` in the container. Docker is configured to use the `json-file` logging driver with rotation (`max-size: 10m`).

## Troubleshooting

### Speaker Diarization is Disabled / Word-level + ผู้พูด blocked

**Symptom**: The `/test` page blocks the "Word-level + ผู้พูด" suite, the diarization UI is greyed out with a "⛔ ปิดอยู่" notice, or `POST /v1/tests/run?suite=word-diar` returns HTTP 400.

**Cause**: `DIARIZATION_ENABLED` auto-disables when `HF_TOKEN` is empty (and no local PyAnnote models are present).

**Solution**: Set `HF_TOKEN=<your huggingface token>` in `.env` (accept the [pyannote gated model](https://huggingface.co/pyannote/speaker-diarization-3.1) terms first), or set `DIARIZATION_ENABLED=true` explicitly if you provide local PyAnnote models in `models/`. Restart the server afterwards.

### NVIDIA GPU / NVENC Availability

If video compression falls back to `libx264` unexpectedly, verify that your GPU is exposed to the Docker container properly.

1. **Verify Host GPU:**
   ```bash
   nvidia-smi
   ```
2. **Verify Docker GPU Injection:**
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
   ```
3. **Verify NVENC inside Container:**
   ```bash
   docker exec <container_name> ls /usr/lib/x86_64-linux-gnu/ | grep -E 'libnvidia-encode|libnvcuvid'
   docker exec <container_name> ffmpeg -h encoder=h264_nvenc >/dev/null && echo "h264_nvenc OK"
   ```
   _Solution_: Ensure `NVIDIA_DRIVER_CAPABILITIES=video,compute,utility` is set in your `docker-compose.yml`.

## Limitations

- **Single-Node Persistence**: The system uses SQLite WAL mode. It is designed to run on a single instance/container and does not natively support horizontal scaling out-of-the-box due to local disk persistence and SQLite constraints.
- **Real-time Streaming**: Real-time websocket streaming currently supports the Thai language only (via Typhoon ASR).
- **Speaker Diarization Requires Credentials**: Diarization needs `HF_TOKEN` for PyAnnote/WhisperX gated models (or local model files in `models/`). Without it, the feature is auto-disabled (`DIARIZATION_ENABLED` auto-off) and diarization requests are rejected with HTTP 422.
- **GPU Constraints**: Multiple concurrent transcriptions might lead to CUDA OOM errors on GPUs with limited VRAM. The system handles this gracefully using process isolation and CUDA memory resets, but it is recommended to manage concurrent requests based on your hardware.