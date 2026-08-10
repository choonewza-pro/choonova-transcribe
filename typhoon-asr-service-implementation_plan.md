# Implementation Plan: Typhoon ASR Service (Python 3.12 + FastAPI)

## 1. Executive Overview

Based on requirements, we are building **Typhoon ASR Service** with **Python 3.12 + FastAPI + Uvicorn** running on **NVIDIA RTX 4080 (12GB VRAM)** hardware.

The service provides:
1. High-speed REST API endpoints (`/v1/transcribe`) for audio file uploads.
2. Low-latency WebSocket streaming endpoint (`/v1/stream`) for real-time microphone speech recognition.
3. Embedded modern HTML/CSS/JS Dashboard with 3 dedicated pages (Home, File Upload Test, Real-time Mic Test).

### Hardware Performance (RTX 4080 12GB VRAM)
- **Model VRAM Footprint**: Typhoon ASR Realtime (114M parameters) requires **< 1 GB VRAM** in FP16 precision.
- **VRAM Headroom**: Consumes < 8% of VRAM, leaving > 11GB VRAM for Ollama LLMs (`qwen2.5`, `gemma2`) and other services.
- **Inference Speed**: ~4,000x RTFx throughput on CUDA cores (1-minute audio transcribed in < 0.1 sec).

---

## 2. Web Application & Dashboard UI Specification

The web interface will feature a premium, dark-mode glassmorphism design (using Google Fonts Outfit/Inter and modern CSS animations) with 3 separate route URLs:

### Page 1: Home / Documentation (`GET /`)
- **Purpose**: System overview, API sitemap, architecture diagrams, and quick-access navigation cards to the test pages.
- **Features**:
  - Technical model specs (FastConformer-Transducer 114M, CER: 0.0984, 4097x RTFx).
  - API documentation snippets (cURL, Python, JavaScript fetch).
  - Navigation links to **File Upload Tester** and **Real-Time Mic Tester**.

### Page 2: Audio File Upload Tester (`GET /test/upload`)
- **Purpose**: Test transcribing pre-recorded audio files.
- **Features**:
  - Drag-and-drop file upload zone (supports `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`).
  - Audio waveform player preview.
  - Options: Enable/Disable estimated word timestamps (`with_timestamps`).
  - Real-time response stats (Execution Time, Audio Duration, Real-time Factor / RTF).
  - Transcription result text box with one-click copy & JSON response inspector.

### Page 3: Real-Time Microphone Speech-to-Text (`GET /test/realtime`)
- **Purpose**: Test live microphone recording with real-time speech transcription.
- **Features**:
  - **Microphone Control**: Single "Start Listening / Stop Listening" button with pulsing recording animation.
  - **Browser Audio Capture**: Uses Web Audio API / `MediaRecorder` (PCM 16kHz audio chunking).
  - **Live WebSocket Stream**: Streams 250ms audio chunks over WebSocket (`ws://host/v1/stream`) to backend.
  - **Real-time Display**: Live updating transcript box as the user speaks with partial and finalized transcript highlights.
  - **Visualizer**: Dynamic audio level / frequency waveform visualizer when mic is active.

---

## 3. API & WebSocket Architecture

### REST API: Audio File Transcription (`POST /v1/transcribe`)
- **Auth**: `Authorization: Bearer <GATEWAY_API_KEY>` or `x-api-key: <GATEWAY_API_KEY>`
- **Body**: `multipart/form-data` (file) or JSON (`audio_data` base64).
- **Response**:
```json
{
  "status": "success",
  "text": "ข้อความภาษาไทยที่แปลงได้จากไฟล์เสียง",
  "duration_seconds": 4.15,
  "rtf": 0.012,
  "timestamps": [
    { "word": "ข้อความ", "start": 0.12, "end": 0.45 },
    { "word": "ภาษาไทย", "start": 0.46, "end": 0.85 }
  ]
}
```

### WebSocket API: Real-Time Audio Streaming (`WS /v1/stream`)
- **Protocol**: Client connects via WebSocket, sends binary PCM/WebM audio frames.
- **Backend Processing**: Receives audio buffer -> appends to stream buffer -> invokes `asr_engine` -> emits partial transcription frames.
- **Server Frame Response**:
```json
{
  "type": "partial",
  "text": "กำลังทดสอบถอดความ...",
  "is_final": false
}
```

---

## 4. Service Directory Structure

```
services/typhoon-asr-service/
├── .env.example
├── .gitignore
├── Dockerfile
├── Dockerfile.cpu
├── README.md
├── requirements.txt
├── requirements-cpu.txt
├── model/
│   ├── README.md
│   └── typhoon-asr-realtime.nemo
└── app/
    ├── __init__.py
    ├── main.py              (FastAPI app, routes & WebSocket handler)
    ├── config.py            (Environment settings & GATEWAY_API_KEY auth)
    ├── auth.py              (Bearer & x-api-key authentication middleware)
    ├── schemas.py           (Pydantic response models)
    ├── asr_engine.py        (Typhoon ASR engine singleton wrapper)
    ├── static/
    │   ├── css/
    │   │   └── style.css    (Dark glassmorphism design system)
    │   └── js/
    │       ├── upload.js    (File upload tester logic)
    │       └── realtime.js  (Web Audio API & WebSocket live recording logic)
    └── templates/
        ├── index.html       (Home & Documentation page)
        ├── upload.html      (Audio File Upload Tester page)
        └── realtime.html    (Real-time Microphone Tester page)
```

---

## 5. Model Download & Docker Caching Strategy (Selected: Option 1)

เพื่อไม่ให้ Git Repository มีขนาดใหญ่เกินไปจากการ Commit ไฟล์โมเดล binary (462 MB) เข้า Git เราจะใช้ **Option 1: Docker Build-time Layer Cache**:

### กลไกการทำงานใน `Dockerfile`:
```dockerfile
# 1. ติดตั้ง huggingface_hub ก่อน
RUN pip install --no-cache-dir huggingface_hub

# 2. ดาวน์โหลดโมเดล typhoon-asr-realtime.nemo มาเก็บไว้ที่ /app/model ในระดับ Layer
# บรรทัดนี้จะถูก Docker Cache ไว้ หากแก้ซอร์สโค้ดใน /app จะไม่ถูก re-download ใหม่แน่นอน
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='typhoon-ai/typhoon-asr-realtime', filename='typhoon-asr-realtime.nemo', local_dir='/app/model')"

# 3. คัดลอกซอร์สโค้ดอยู่ด้านล่างเพื่อให้ใช้ประโยชน์จาก Build Cache ได้เต็มที่
COPY app /app
```

### การตั้งค่า Git (`.gitignore`):
- ใส่ `services/typhoon-asr-service/model/*.nemo` ลงใน `.gitignore` เพื่อป้องกันไม่ให้ไฟล์โมเดลหลุดเข้าไปใน Git Repository
- เมื่อใดก็ตามที่มีคน `git clone` โครงการไปรันใหม่ เพียงแค่สั่ง `docker compose up --build` ตัว Docker จะทำการดาวน์โหลดโมเดลมาสร้าง Image ให้โดยอัตโนมัติเองครับ

---

## 6. Docker & Integration Strategy

- **Port Allocation**: Port `8830` (following `nsfw-detector` at 8810 and `pdf-ocr` at 8820).
- **GPU Dockerfile (`Dockerfile`)**: `nvidia/cuda:12.1.0-runtime-ubuntu22.04` base with PyTorch 2.4+ GPU.
- **CPU Dockerfile (`Dockerfile.cpu`)**: `python:3.12-slim` image for CPU-only execution.
- **Root `docker-compose.yml` Integration**:
```yaml
  # =========================================================================
  # 8. Typhoon ASR Service: Python 3.12 FastAPI + NeMo Typhoon ASR Realtime
  # =========================================================================
  typhoon-asr-service:
    build:
      context: ./services/typhoon-asr-service
      dockerfile: Dockerfile
    image: choonova-typhoon-asr:latest
    container_name: choonova-typhoon-asr
    restart: unless-stopped
    ports:
      - "8830:8830"
    environment:
      - HOST=0.0.0.0
      - PORT=8830
      - GATEWAY_API_KEY=change-me-in-production
      - MODEL_PATH=/app/model/typhoon-asr-realtime.nemo
      - LOG_LEVEL=info
    volumes:
      - ./services/typhoon-asr-service/model:/app/model:ro
      - ./services/typhoon-asr-service/app:/app/app
    networks:
      - km4u-network
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8830/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```
- **Root `docker-compose-cpu.yml` Integration**: Same service definition using `dockerfile: Dockerfile.cpu` without GPU reservations.

---

## 6. Proposed Implementation Steps

1. **Step 1: Project Setup & Dependencies**
   - Create `services/typhoon-asr-service/requirements.txt` (`fastapi`, `uvicorn`, `typhoon-asr`, `jinja2`, `torch`, `python-multipart`, `websockets`).

2. **Step 2: Core Engine & Auth (`app/asr_engine.py`, `app/auth.py`, `app/config.py`)**
   - Build Typhoon ASR model loader singleton and transcription methods (file transcribe & streaming chunks).

3. **Step 3: API & WebSocket Endpoints (`app/main.py`)**
   - Implement `POST /v1/transcribe` and `WS /v1/stream`.

4. **Step 4: Premium UI Dashboard Pages & Static Assets**
   - Create Home (`/`), Audio File Upload (`/test/upload`), and Real-time Mic (`/test/realtime`) UI pages with dark glassmorphism styling.

5. **Step 5: Docker & Docker-Compose Integration**
   - Create `Dockerfile` & `Dockerfile.cpu` under `services/typhoon-asr-service/`.
   - Update root `docker-compose.yml` and `docker-compose-cpu.yml` to include `typhoon-asr-service`.

6. **Step 6: Testing & Verification**
   - Verify audio file upload transcription accuracy.
   - Verify live microphone real-time streaming WebSocket transcription.
