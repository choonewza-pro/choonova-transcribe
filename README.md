# ChooNova Transcribe

<p align="center">
  <img src="app/static/choonova-transcribe-cover-1.png" alt="ChooNova Transcribe Cover" width="100%" style="max-width: 900px; border-radius: 12px;">
</p>

Thai Speech-to-Text API and video processing service powered by Typhoon ASR Realtime & Faster Whisper.

> 💡 **For AI Coding Agents:** Please read [project-onboarding SKILL.md](file://.agents/skills/project-onboarding/SKILL.md) for setup instructions and architecture details before modifying this project.

## Overview

ChooNova Transcribe is a high-performance audio transcription and media processing API. It leverages NeMo Toolkit and the Typhoon ASR Realtime model (FastConformer-Transducer 114M) to provide fast and accurate Thai speech-to-text capabilities. The service supports both REST APIs for batch processing and WebSockets for real-time streaming, and includes a built-in video compressor using FFmpeg. It is designed to run efficiently on both NVIDIA GPUs (CUDA 12.1) and CPUs.

## Key Features

- **Real-time Transcription**: WebSocket endpoint (`/v1/realtime/stream`) for live microphone transcription in 250ms chunks (Thai only).
- **Short Audio Transcription**: REST API for quick, synchronous processing of short multipart audio uploads.
- **Long-form Media Pipeline**: Asynchronous processing for large video/audio files (up to 1GB+) with silence-aware chunking and automatic cleanup.
- **Auto Language Detection**: Seamlessly fallback to faster-whisper for English or code-switched (Thai-English) content.
- **Video Compression**: Asynchronous FFmpeg-based video compressor with queue management, supporting both CPU (libx264) and GPU (NVENC) encoding.
- **Job History & Management**: Built-in SQLite tracking for transcription and compression jobs with a web-based dashboard.
- **Dynamic VRAM Management**: Configurable model residency (Always-on vs. Idle timeout) to optimize GPU memory usage.

## Architecture

ChooNova Transcribe follows a Pragmatic Modular Monolith + Hexagonal Architecture:

- **API Delivery**: FastAPI routers grouped by bounded context (Settings, Compression, Transcription, Realtime).
- **Isolated Workers**: Long-running jobs (transcription and compression) execute in isolated subprocesses (`job_worker.py`, `run_compress_job.py`) to prevent top-level RAM/VRAM leaks. A watchdog process monitors and recovers from worker crashes.
- **CUDA Resilience**: Implements transient error retries (with backoff) and allocator corruption recovery via `cudaDeviceReset`.

## Technology Stack

| Layer         | Technology                 | Purpose                                              |
| ------------- | -------------------------- | ---------------------------------------------------- |
| Language      | Python 3.12                | Core application logic                               |
| Web Framework | FastAPI + Uvicorn          | High-performance async HTTP/WebSocket server         |
| Deep Learning | PyTorch 2.5.1              | Tensor operations and model execution (CUDA 12.1)    |
| ASR Models    | NeMo Toolkit ≥2.0          | Inference for Typhoon ASR and faster-whisper         |
| Audio/Video   | FFmpeg, librosa, soundfile | Media extraction, silence detection, and compression |
| Storage       | SQLite (WAL mode)          | Transactional job history and settings persistence   |

## Requirements

**Recommended (GPU):**

- NVIDIA GPU with at least 12GB VRAM (Tested on RTX 4080 Laptop GPU)
- NVIDIA Container Toolkit (for Docker deployments)
- CUDA 12.1 (for local development)

**Supported (CPU Fallback):**

- Windows, Mac M1–M4, or Linux CPUs

## Quick Start

The shortest path to running the service is via Docker. The image includes an empty SQLite database so it runs immediately without external dependencies. If you wish to persist job history across container restarts, mount the `./data:/app/data` volume in `docker-compose.yml`.

**GPU (Requires NVIDIA Docker)**

```bash
docker compose up -d --build
```

**CPU (Windows / Mac / Linux)**

```bash
docker compose -f docker-compose-cpu.yml up -d --build
```

The service dashboard and API will be available at `http://localhost:8830/`.

## Configuration

Application behavior is controlled via environment variables. Copy `.env.example` to `.env` to configure the service.

| Variable                   | Default                   | Required | Description                                                                 |
| -------------------------- | ------------------------- | -------- | --------------------------------------------------------------------------- |
| `GATEWAY_API_KEY`          | `change-me-in-production` | Yes      | Secret key for API authentication.                                          |
| `DEVICE`                   | `cuda`                    | No       | Target device (`cuda` or `cpu`). Auto-detects if CUDA is missing.           |
| `WHISPER_MODEL`            | `medium`                  | No       | faster-whisper size (`tiny/base/small/medium/large-v3`).                    |
| `MODEL_LOAD_MODE`          | `always`                  | No       | VRAM residency seed: `always` or `idle`.                                    |
| `MODEL_IDLE_TIMEOUT_SEC`   | `900`                     | No       | Seconds of inactivity before unloading models (if `idle`).                  |
| `COMPRESS_ENCODER`         | `libx264`                 | No       | Video encoder: `libx264` or `nvenc` (auto-falls back if NVENC unavailable). |
| `MAX_AUDIO_UPLOAD_SIZE_MB` | `50.0`                    | No       | Size limit for synchronous audio endpoint.                                  |
| `MAX_UPLOAD_SIZE_MB`       | `0`                       | No       | Size limit for async long-form jobs (0 = unlimited).                        |
| `MAX_MEDIA_DURATION_SEC`   | `14400.0`                 | No       | Max duration in seconds for uploaded media to prevent GPU hogging.          |

_(Note: Environment variables for VRAM mode only seed the database on first boot. The database is the source of truth thereafter.)_

## Authentication / Security

- **API Endpoints**: All `/v1` REST endpoints require a static API key passed via the `x-api-key` HTTP header. The system uses constant-time HMAC comparison to verify keys.
- **Web UI & WebSockets**: Unauthenticated for ease of local access and streaming.
- **Upload Validation (Defense-in-Depth)**: All file uploads undergo multi-layer inspection before processing:
  - Extension and Size verification.
  - Magic Bytes signature checking (`filetype`) to prevent file masking.
  - Deep container inspection via `ffprobe` to reject malicious Polyglot files.
  - Safe filename sanitization to prevent Path Traversal attacks.
- **Subprocess & FFmpeg Security**: FFmpeg executions run securely without `shell=True` and enforce `-protocol_whitelist file,pipe,crypto` to completely eliminate Server-Side Request Forgery (SSRF) risks from malicious media playlists (e.g., weaponized `.m3u8`).

## Usage: Model VRAM Residency

The ASR models (Typhoon + Whisper) consume significant GPU memory (~1GB+). Their lifecycle is managed in two modes:

- **`always`** (Default): Models remain in VRAM permanently once loaded. Best for low latency.
- **`idle`**: Models are unloaded after `MODEL_IDLE_TIMEOUT_SEC` of inactivity. The next request pays a cold-start cost (~10-60s) to reload.

You can toggle this mode at runtime without restarting the server via the web dashboard (`/setting`) or the `PUT /v1/settings/model` endpoint.

## API Reference

### REST Endpoints

| Method | Path                                             | Auth | Description                                        |
| ------ | ------------------------------------------------ | ---- | -------------------------------------------------- |
| POST   | `/v1/audio/transcribe`                           | ✅   | Synchronously transcribe short audio (multipart).  |
| POST   | `/v1/media/transcribe/jobs`                      | ✅   | Enqueue long-form transcription job (returns 202). |
| GET    | `/v1/media/transcribe/jobs/{id}`                 | ✅   | Check status and retrieve transcription results.   |
| GET    | `/v1/media/transcribe/jobs/{id}/export/{format}` | ✅   | Export results as `txt`, `srt`, or `json`.         |
| POST   | `/v1/media/compress/jobs`                        | ✅   | Enqueue video compression job (returns 202).       |
| GET    | `/v1/media/compress/jobs/{id}/download`          | ✅   | Download the compressed MP4 output.                |
| PUT    | `/v1/settings/model`                             | ✅   | Change model VRAM mode at runtime.                 |

### cURL Examples

**Short Audio Transcription (Thai - default via Typhoon ASR)**

```bash
curl -X POST http://localhost:8830/v1/audio/transcribe \
  -H "x-api-key: change-me-in-production" \
  -F "file=@audio.mp3" -F "language=th" -F "with_timestamps=true"
```

**Long-form Video Transcription (Auto-detect Language - Whisper)**

```bash
curl -X POST http://localhost:8830/v1/media/transcribe/jobs \
  -H "x-api-key: change-me-in-production" \
  -F "file=@video.mp4" -F "language=auto"
```

**Video Compression (Resize & Trim)**

```bash
curl -X POST http://localhost:8830/v1/media/compress/jobs \
  -H "x-api-key: change-me-in-production" \
  -F "file=@video.mp4" -F "target_width=1280" -F "bitrate_kbps=2000" \
  -F "start=00:01:00" -F "end=00:02:00"
```

### WebSocket Streaming

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
   │ (Returns 202 Accepted → job_id)
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
   │ (Returns 202 Accepted → job_id + queue position)
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
tests/
└── unit/            # Unit tests using in-memory Fake adapters
```

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
