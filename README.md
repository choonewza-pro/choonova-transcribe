# ChooNova Transcribe

<p align="center">
  <img src="app/static/choonova-transcribe-cover.png" alt="ChooNova Transcribe Cover" width="100%" style="max-width: 900px; border-radius: 12px;">
</p>

Thai Speech-to-Text API and video processing service powered by Typhoon ASR Realtime & Faster Whisper (`large-v3-turbo`).

> 💡 **For Developers & AI Agents:** See [project-onboarding SKILL.md](file://.agents/skills/project-onboarding/SKILL.md) for setup and [knowledges/](file://knowledges/) for deep-dive technical architecture documents.

## Overview

ChooNova Transcribe is a high-performance audio transcription and media processing API. It leverages NeMo Toolkit and the Typhoon ASR Realtime model (FastConformer-Transducer 114M) to provide fast and accurate Thai speech-to-text capabilities. The service supports both REST APIs for batch processing and WebSockets for real-time streaming, and includes a built-in video compressor using FFmpeg. It is designed to run efficiently on both NVIDIA GPUs (CUDA 12.1) and CPUs.

## Key Features

- **OpenAI-Compatible Audio API**: Full drop-in replacement for OpenAI Whisper API (`/v1/audio/transcriptions`, `/v1/audio/translations`, `/v1/models`). Seamlessly integrates with official OpenAI Python/Node SDKs, Open WebUI, Obsidian, and third-party clients. Supports output formats: `json`, `text`, `srt`, `vtt`, and `verbose_json` (with `timestamp_granularities[]`).
- **Real-time Transcription**: High-performance WebSocket endpoint (`/v1/realtime/stream`) for zero-disk-write live microphone transcription with in-memory FFmpeg pipes, 600ms streaming updates, and sliding window preview (Thai only).
- **Short Audio Transcription & Translation**: REST API for quick, synchronous processing of short multipart audio uploads, including speech-to-English translation (`task="translate"`).
- **Long-form Media Pipeline**: Asynchronous processing for large video/audio files (up to 1GB+) with silence-aware chunking and automatic cleanup.
- **Auto Language Detection & Secondary ASR**: Uses **Faster Whisper (`large-v3-turbo`)** (~809M params) for English, Thai-English mixed content, and speech-to-English translation, delivering 4-6x faster decoding speed than standard Large-v3 with low VRAM footprint (~3.5GB).
- **Speaker Diarization with Speaker Count Controls**: Multi-speaker identification and labeling (`[SPEAKER_00]`, `[SPEAKER_01]`, ...) powered by PyAnnote 3.1 & WhisperX. Supports explicit speaker count controls (`num_speakers`, `min_speakers`, `max_speakers`) to lock clustering and maximize accuracy. Uses a 4 Pathways Matrix with automatic VRAM swapping and graceful fallback.
- **Video Compression**: Asynchronous FFmpeg-based video compressor with queue management, supporting both CPU (libx264) and GPU (NVENC) encoding.
- **Job History & Management**: Built-in SQLite tracking for transcription and compression jobs with a web-based dashboard and export capabilities (.txt, .srt, .json).
- **Dynamic VRAM Management**: Configurable model residency (Always-on vs. Idle timeout) to optimize GPU memory usage.

## Architecture

ChooNova Transcribe follows a Pragmatic Modular Monolith + Hexagonal Architecture:

- **API Delivery**: FastAPI routers (`app/api/v1/`) use clean Hexagonal Architecture patterns, decoupling delivery from domain logic via service factories.
- **Isolated Workers & Background Tasks (Legacy/Monolithic Hybrid)**: Long-running jobs (transcription and compression) and background watchdogs run as isolated subprocesses ([`job_worker.py`](file:///D:/_PROJECT_/choonova-transcribe/app/job_worker.py), [`compress_worker.py`](file:///D:/_PROJECT_/choonova-transcribe/app/compress_worker.py)) using monolithic connections ([`app/db.py`](file:///D:/_PROJECT_/choonova-transcribe/app/db.py)).
- **CUDA Resilience**: Implements transient error retries (with backoff) and allocator corruption recovery via `cudaDeviceReset`.

### 4 Pathways Processing Matrix

Depending on the requested language (`th` vs. `en`/`auto`) and whether speaker diarization is enabled (`enable_diarization`), the pipeline routes jobs across 4 distinct pathways:

| Pathway | Language | Diarization | Engine & Pipeline | Mechanism & Rationale |
|---|---|---|---|---|
| **Path 1** | `th` | ❌ Disabled | **Typhoon ASR** | FastConformer-Transducer 114M (~1GB VRAM). Fastest and most accurate for pure Thai audio. |
| **Path 2** | `en` / `auto` | ❌ Disabled | **Faster Whisper** | CTranslate2 `large-v3-turbo` (~3.5GB VRAM). Ideal for English and auto language detection. |
| **Path 3** | `th` | ✅ Enabled | **Typhoon ASR + PyAnnote 3.1** | Typhoon ASR $\rightarrow$ PyAnnote 3.1 Diarization $\rightarrow$ **Maximum-Overlap Merge** with nearest-neighbor fallback. (WhisperX lacks default forced alignment models for Thai). |
| **Path 4** | `en` / `auto` | ✅ Enabled | **WhisperX** | Transcribe $\rightarrow$ Phoneme Forced Alignment (wav2vec2) $\rightarrow$ PyAnnote 3.1 Diarization $\rightarrow$ Word Speaker Assignment. Provides word-level speaker accuracy. |

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
| ASR Models    | NeMo Toolkit & Faster Whisper         | Typhoon ASR (114M) & Faster Whisper (`large-v3-turbo`) |
| Diarization   | PyAnnote.audio 3.1 & WhisperX         | Multi-speaker identification and word alignment      |
| Audio/Video   | FFmpeg, librosa, soundfile            | Media extraction, silence detection, and compression |
| Storage       | SQLite (WAL mode)                     | Transactional job history and settings persistence   |

## Requirements

**Required:**

- Docker and Docker Compose
- Minimum 5GB Free Disk Space (`MIN_FREE_DISK_GB`)

**Recommended (GPU):**

- NVIDIA GPU with at least 12GB VRAM (Tested on RTX 4080 Laptop GPU)
- NVIDIA Container Toolkit (for Docker deployments)
- CUDA 12.1 (for local development)

**Supported (CPU Fallback):**

- Windows, Mac M1–M4, or Linux CPUs

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
5. **Open the app** at [http://localhost:8830](http://localhost:8830)
6. **Verify the service is working (after installation)**
   - Go to the **API Self-Test** page: [http://localhost:8830/test](http://localhost:8830/test)
   - The page is only accessible once you have set an API Key (enter it on `/setting` or use `http://localhost:8830/test?api_key=YOUR_KEY`)
   - Press the **▶ Start Automated Test** button — the service sends sample files from the `assets/` folder to the real endpoints (Thai transcription + video compression) and reports pass/fail per test, with an `X/N` progress bar
   - Video compression can take several minutes (especially in CPU mode) — the progress bar keeps you informed while the job is running

## Configuration

Application behavior is controlled via environment variables. Copy `.env.example` to `.env` to configure the service.

| Variable                     | Default                   | Required | Description                                                                 |
| ---------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `GATEWAY_API_KEY`            | `change-me-in-production` | Yes      | Secret key for API authentication.                                          |
| `DEVICE`                     | `cuda`                    | No       | Target device (`cuda` or `cpu`). Auto-detects if CUDA is missing.           |
| `WHISPER_MODEL`              | `large-v3-turbo`          | No       | faster-whisper model size (`large-v3-turbo`, `large-v3`, `medium`, `small`, etc.). |
| `HF_TOKEN`                   | *(Empty)*                 | No       | Hugging Face Hub token. Required for PyAnnote 3.1 & WhisperX gated models (`pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`). |
| `DIARIZATION_ENABLED`        | `true`                    | No       | Master toggle for speaker diarization feature (`true` or `false`).          |
| `DIARIZATION_MODEL`          | `pyannote/speaker-diarization-3.1` | No | Hugging Face model ID for PyAnnote diarization pipeline.                     |
| `DIARIZATION_MIN_SPEAKERS`   | *(Empty)*                 | No       | Optional hint for minimum expected speakers (auto-detect if empty).          |
| `DIARIZATION_MAX_SPEAKERS`   | *(Empty)*                 | No       | Optional hint for maximum expected speakers (auto-detect if empty).          |
| `MODEL_LOAD_MODE`            | `always`                  | No       | VRAM residency seed: `always` or `idle`.                                    |
| `MODEL_IDLE_TIMEOUT_SEC`     | `900`                     | No       | Seconds of inactivity before unloading models (if `idle`).                  |
| `COMPRESS_ENCODER`           | `libx264`                 | No       | Video encoder: `libx264` or `nvenc` (auto-falls back if NVENC unavailable). |
| `COMPRESS_MAX_CONCURRENT`    | `1`                       | No       | Maximum concurrent compression jobs.                                        |
| `COMPRESS_MAX_QUEUED`        | `10`                      | No       | Maximum jobs waiting in compression queue.                                  |
| `COMPRESS_RETENTION_HOURS`   | `24`                      | No       | Hours to retain compressed output files on disk.                            |
| `TRANSCRIBE_MAX_CONCURRENT`  | `1`                       | No       | Maximum concurrent transcription jobs.                                      |
| `TRANSCRIBE_MAX_QUEUED`      | `10`                      | No       | Maximum jobs waiting in transcription queue before returning 429.          |
| `TRANSCRIBE_RETENTION_HOURS` | `24`                      | No       | Hours to retain transcription media files on disk.                          |
| `TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC` | `45.0` | No | Target chunk size for Typhoon ASR (Thai) silence-based splitting. |
| `TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC` | `90.0` | No | Max chunk size for Typhoon ASR (Thai) silence-based splitting. |
| `TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC` | `25.0` | No | Target chunk size for Whisper (English/Auto) silence-based splitting. |
| `TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC` | `30.0` | No | Max chunk size for Whisper (English/Auto) silence-based splitting. |
| `MAX_AUDIO_UPLOAD_SIZE_MB`   | `50.0`                    | No       | Size limit for synchronous audio endpoint.                                  |
| `MAX_UPLOAD_SIZE_MB`         | `0`                       | No       | Size limit for async long-form jobs (0 = unlimited).                        |
| `MAX_MEDIA_DURATION_SEC`     | `21600.0`                 | No       | Max duration in seconds for uploaded media to prevent GPU hogging.          |
| `MAX_AUDIO_DURATION_SEC`     | `3600.0`                  | No       | Max duration in seconds for short audio endpoints (full-file single-pass).  |
| `MIN_FREE_DISK_GB`           | `5.0`                     | No       | Minimum required free disk space in GB before rejecting new jobs.           |
| `ALLOW_ACCESS_TRANSCRIBE_HISTORY` | `false`              | No       | Bypasses API key authentication on ASR history. **⚠️ SECURITY RISK**: Enabling this allows public access to transcripts and media files. |
| `ALLOW_ACCESS_COMPRESS_HISTORY` | `false`                | No       | Bypasses API key authentication on compress history. **⚠️ SECURITY RISK**: Enabling this allows public access to compression logs and videos. |

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

- Transcribe short audio directly.
- Stream microphone audio in real-time.
- Upload long videos for asynchronous transcription and monitor progress.
- Compress videos.
- Adjust Model VRAM Settings.
- Run the automated API self-test (`/test`) to verify every endpoint works end-to-end.

### Model VRAM Residency

The ASR models (Typhoon + Whisper) consume significant GPU memory (~1GB+). Their lifecycle is managed in two modes:

- **`always`** (Default): Models remain in VRAM permanently once loaded. Best for low latency.
- **`idle`**: Models are unloaded after `MODEL_IDLE_TIMEOUT_SEC` of inactivity. The next request pays a cold-start cost (~10-60s) to reload.

You can toggle this mode at runtime without restarting the server via the web dashboard (`/setting`) or the `PUT /v1/settings/model` endpoint.

## API Reference

### REST Endpoints

| Method | Path                                             | Auth | Description                                        |
| ------ | ------------------------------------------------ | ---- | -------------------------------------------------- |
| POST   | `/v1/audio/transcriptions`                       | ✅   | **OpenAI Drop-in**: Transcribe audio (JSON/SRT/VTT/verbose_json). |
| POST   | `/v1/audio/translations`                         | ✅   | **OpenAI Drop-in**: Translate audio to English text. |
| GET    | `/v1/models`                                     | ❌   | **OpenAI Drop-in**: List available models (`whisper-1`, `typhoon-asr`). |
| GET    | `/v1/models/{model_id}`                          | ❌   | **OpenAI Drop-in**: Retrieve model metadata.       |
| POST   | `/v1/audio/transcribe`                           | ✅   | Synchronously transcribe short audio (multipart).  |
| POST   | `/v1/media/transcribe/jobs`                      | ✅   | Enqueue long-form transcription job (returns 202). |
| GET    | `/v1/media/transcribe/jobs/{id}`                 | ✅   | Check status and retrieve transcription results.   |
| GET    | `/v1/media/transcribe/jobs/{id}/export/{format}` | ✅   | Export results as `txt`, `srt`, or `json`.         |
| POST   | `/v1/media/compress/jobs`                        | ✅   | Enqueue video compression job (returns 202).       |
| GET    | `/v1/media/compress/jobs/{id}/download`          | ✅   | Download the compressed MP4 output.                |
| PUT    | `/v1/settings/model`                             | ✅   | Change model VRAM mode at runtime.                 |

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

# Translate audio to English
with open("thai_speech.mp3", "rb") as audio_file:
    translation = client.audio.translations.create(
        model="whisper-1",
        file=audio_file
    )
print(translation.text)
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

**Short Audio Transcription (Thai - Typhoon ASR)**

```bash
curl -X POST http://localhost:8830/v1/audio/transcribe \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@audio.mp3" -F "language=th" -F "with_timestamps=true"
```

**Long-form Video Transcription with Exact Speaker Count**

```bash
curl -X POST http://localhost:8830/v1/media/transcribe/jobs \
  -H "Authorization: Bearer change-me-in-production" \
  -F "file=@meeting.mp4" -F "language=th" -F "enable_diarization=true" -F "num_speakers=2"
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
job_worker.py (isolated subprocess)
   ├─ 1. FFmpeg extract → 16kHz mono 16-bit WAV
   ├─ 2. Silence-aware chunking (target 30s, max 60s, overlap 0.25s)
   ├─ 3. GPU transcription loop (with global asyncio.Lock)
   ├─ 4. Build full text + timestamps + SRT
   └─ 5. Save results to SQLite & cleanup temp files
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
   ├─ 2. FFmpeg encode (scale, bitrate/CRF, libx264/nvenc)
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
# GPU environment
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU environment
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
```

## Testing

The project uses the standard `unittest` library with fake in-memory repositories (no mocking framework) to test domain logic in isolation.

```bash
python -m unittest discover -s tests/unit -t . -v
```

## Project Structure

```
app/
├── main.py          # FastAPI application entry point
├── *worker.py       # Isolated subprocess workers (Transcription, Compression)
├── core/            # Cross-cutting concerns (config, db, security)
├── modules/         # Domain bounded contexts (settings, compression, transcription)
├── api/             # Delivery layer
│   ├── v1/          # REST & WebSocket API routers
│   └── web/         # HTML Dashboard view routers
├── templates/       # Jinja2 HTML templates
└── static/          # Vanilla CSS & JS assets
knowledges/          # 📚 Technical knowledge base & architecture deep-dives for study/reference
tests/
└── unit/            # Unit tests using in-memory Fake adapters
```

## Deployment / Operations

- **Container Deployment**: Docker Compose is the recommended deployment strategy. The `km4u-network` external network must be created beforehand (`docker network create km4u-network`) if integrating with other services, or you can remove the external network constraint in `docker-compose.yml` for standalone use.
- **Persistent Storage**: Ensure you mount `./data:/app/data` to persist job histories and application settings across restarts.
- **Observability**: Uvicorn access logs and application logs are outputted to `stdout` in the container. Docker is configured to use the `json-file` logging driver with rotation (`max-size: 10m`).

## Troubleshooting

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
- **GPU Constraints**: Multiple concurrent transcriptions might lead to CUDA OOM errors on GPUs with limited VRAM. The system handles this gracefully using process isolation and CUDA memory resets, but it is recommended to manage concurrent requests based on your hardware.
