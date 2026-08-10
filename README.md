# บริการถอดเสียงภาษาไทย Typhoon ASR Realtime (Typhoon ASR Service)

Speech-to-Text API บริการภาษาไทย powered by **Typhoon ASR Realtime** (โมเดล FastConformer-Transducer 114M parameters) บน **Python 3.12 + FastAPI + NeMo Toolkit** ออกแบบให้รันบน **NVIDIA RTX 4080 (12GB VRAM)** พร้อม Docker Compose กับ stack ชุดเดียวกัน (Ollama, Gateway, Webapp, NSFW Detector, PDF OCR)

รองรับ 4 โหมดการใช้งาน:
1. **REST API** (`POST /v1/transcribe`) — ถอดความไฟล์เสียงสั้น ผ่าน upload แบบ multipart
2. **WebSocket Real-time** (`/v1/stream`) — ถอดเสียงสดจากไมค์ ผ่าน chunk 250ms
3. **Long-form Video Pipeline** (`POST /v1/transcribe/jobs`) — ไฟล์วิดีโอ/เสียงยาวสูงสุด 1GB+ / 3+ ชั่วโมง ทำงานเบื้องหลัง (async 202 Accepted)
4. **ประวัติการถอดความ** (`/test/jobs`) — เรียกดูข้อมูลการถอดเสียงแต่ละรายการภายหลัง พร้อม export และจัดการไฟล์ media

Model footprint เล็กมาก (~1GB VRAM FP16, <8% ของ 12GB) เหลือ VRAM ให้ Ollama LLMs ทำงานร่วมกันได้

---

## 🏗️ สถาปัตยกรรมระบบ (Architecture)

### Tech Stack
| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web Framework | FastAPI + Uvicorn |
| ASR Model | NeMo Toolkit ≥2.0, Typhoon ASR Realtime (`.nemo`) |
| Deep Learning | PyTorch 2.5.1 (+ CUDA 12.1) |
| Audio Processing | FFmpeg, librosa, soundfile |
| Storage | SQLite (jobs history), filesystem (temp jobs) |
| Frontend | Vanilla HTML/CSS/JS + Jinja2 templates (glassmorphism dark UI) |

### โครงสร้างโปรเจค (Directory Tree)
```
services/typhoon-asr-service/
├── app/
│   ├── main.py          # FastAPI app, route registration, WebSocket, periodic cleanup
│   ├── config.py        # Environment configuration & defaults
│   ├── auth.py          # API key verification (Bearer / x-api-key / ?api_key=)
│   ├── db.py            # SQLite repository for jobs + retention cleanup
│   ├── schemas.py       # Pydantic request/response models
│   ├── asr_engine.py    # Typhoon ASR model singleton wrapper (NeMo)
│   ├── audio_utils.py   # FFmpeg extract/split, disk-space check, safe_delete helpers
│   ├── job_worker.py    # Async long-form transcription pipeline (chunking + GPU loop)
│   ├── templates/       # HTML pages (index, upload, realtime, media, jobs)
│   └── static/          # CSS + JS (upload.js, realtime.js, media.js, jobs.js)
├── model/               # Model weights (typhoon-asr-realtime.nemo, git-ignored)
├── data/                # SQLite DB (jobs.db) — volume-mounted into containers
├── example_code/        # Reference official SCB-10X implementation
├── Dockerfile           # GPU image (CUDA 12.1, PyTorch)
├── Dockerfile.cpu       # CPU-only image
├── requirements.txt     # GPU dependencies (incl. CUDA PyTorch index)
├── requirements-cpu.txt # CPU dependencies
└── .env.example         # Environment template
```

### ระบบจัดการไฟล์ชั่วคราว (Long-form Flow)
```
POST /v1/transcribe/jobs  (multipart file 1GB+)
        │ 202 Accepted → job_id (async background)
        ▼
job_worker.py (process_transcription_job)
  ├─ 1. FFmpeg extract → 16kHz mono 16-bit WAV  (extracted_audio.wav)
  ├─ 2. Silence-aware chunking → chunks/chunk_*.wav
  │      (target 300s, max 600s, fallback hard cut + 0.25s overlap)
  ├─ 3. GPU transcription loop under global asyncio.Lock (gpu_lock)
  │      → delete each chunk WAV immediately after inference (คุมดิสก์ระหว่างรัน)
  ├─ 4. Build full text + global timestamps + SRT subtitles
  └─ 5. Save result to SQLite (result_text, srt_text, timestamps_json)
         → delete extracted_wav / chunks_dir / input file / job_dir
         → status=completed
```

> ไฟล์ media ต้นฉบับจะถูกลบอัตโนมัติหลังประมวลผลเสร็จหรือล้มเหลว (ตาม design เดิม) — ข้อมูลถอดความ (text/SRT/timestamps) ถูกเก็บใน SQLite จึง export ได้เสมอแม้ไฟล์บนดิสก์ถูกลบไปแล้ว

---

## 🔒 ฟีเจอร์หลักและการทำงาน (Core Features & Logic)

### 1. REST Audio Transcription — `POST /v1/transcribe`
- รับไฟล์เสียง (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`) แบบ `multipart/form-data`
- ตัวเลือก `with_timestamps` คำนวณ word-level timestamps (เฉลี่ยจาก duration)
- Response: `text`, `duration_seconds`, `elapsed_seconds`, `rtf`, `timestamps`

### 2. Real-time WebSocket — `/v1/stream`
- รับ audio chunk 250ms (WebM) ตลอดการพูด; buffer กันไว้ ~15 วินาที (480,000 bytes)
- Command protocol (text message): `CLEAR` (reset), `COMMIT_SEGMENT` (final), `INTERIM` (partial)
- `remove_text_overlap()` ตัดคำซ้ำตรงรอยต่อ segment ป้องกันข้อความซ้ำซ้อน

### 3. Long-form Video Pipeline — `/v1/transcribe/jobs`
- Upload ใหญ่สุด 1GB+ อัปโหลดแบบ stream 1MB/รอบ (กัน OOM) พร้อมเช็คพื้นที่ดิสก์ (`MIN_FREE_DISK_GB`)
- คืน `job_id` ทันที (202) — ประมวลผล async เบื้องหลัง
- Stage status: `queued → extracting → chunking → transcribing → completed` พร้อม `progress_pct`
- GPU concurrency ควบคุมด้วย `asyncio.Lock` ระดับ process — งานยาวไม่รบกวนงาน realtime
- **CUDA resilience (2 tiers)**: งานยาวที่รัน transcribe ต่อเนื่องหลายๆ ครั้งอาจเจอ error จาก GPU ได้ 2 ชนิด โดยระบบ recover ต่างกัน:
  - **Tier 1 — transient driver error** (เช่น `CUDA driver error: device not ready`): retry แบบ backoff
    (เริ่ม `CUDA_RETRY_BACKOFF_SEC` คูณตามรอบ จำนวน `CUDA_RETRY_ATTEMPTS` รอบ) พร้อม
    `torch.cuda.synchronize()/empty_cache()` ระหว่างรอบ; ถ้ายัง fail ครบ จะบังคับ reload โมเดล
    (`engine.reset()` + `clear_cuda_cache()`) แล้วลองครั้งสุดท้าย
  - **Tier 2 — allocator corruption** (เช่น `!handles_.at(i) INTERNAL ASSERT FAILED at CUDACachingAllocator.cpp`)
    จาก PyTorch allocator handles-map เสียหลัง NeMo transcribe หลายครั้งติดกัน: `empty_cache()` แก้ไม่ได้ —
    ทำ full **CUDA device reset** (`cudaDeviceReset()` + reload โมเดล) แล้วลองใหม่ 1 ครั้ง
  ทำให้ GPU hiccup ครั้งเดียวไม่ทิ้งงานทั้งไฟล์
- Export: `.txt`, `.srt` (subtitle), `.json` (timestamps) ผ่าน `/v1/transcribe/jobs/{id}/export/{format}`

### 4. ประวัติการถอดความ (Transcription History) — `/test/jobs`
- **รายการงาน**: `GET /v1/transcribe/jobs?limit=&include_text=` (default `include_text=false` ตัดคอลัมน์ข้อความหนักๆ) + ฟิลด์ `media_files_exist` (ตรวจไฟล์บนดิสก์)
- **ดูถอดความ**: `GET /v1/transcribe/jobs/{id}` → modal แสดงข้อความเต็ม + ปุ่ม copy / export txt/srt/json (เหมือน `/test/media`)
- **ลบเฉพาะ media**: `DELETE /v1/transcribe/jobs/{id}/media` → ลบเฉพาะไฟล์บนดิสก์เพื่อคืนทรัพยากร แต่ **เก็บ record การถอดความไว้** (งาน completed ที่ไฟล์ถูกลบไปแล้วจะคืน `media_deleted: false`)
- **ลบทั้งแถว**: `DELETE /v1/transcribe/jobs/{id}` → ลบ record + ไฟล์ทั้งหมด

### 5. Disk Cleanup & Retention
- **After pipeline**: ลบไฟล์ทันทีหลังสำเร็จ/ล้มเหลว (input, extracted wav, chunks, job dir)
- **Periodic cleanup (ทุก 1 ชม.)**: งานที่ `completed` อายุเกิน `CLEANUP_RETENTION_HOURS` (default 24h) → **เก็บ record ไว้** (ดูประวัติได้ตลอด) แต่ลบ dir/ไฟล์เหลือ; งาน non-completed (failed/ค้าง) ที่อายุเกิน → ลบ record + dir
- **Zombie recovery**: ตอน startup งานที่ค้างสถานะ processing (จาก crash) จะถูก mark เป็น `failed`
- `safe_delete_file()` / `safe_delete_dir()` (audio_utils.py) ลบเฉพาะเมื่อ path มีอยู่จริง และไม่ raise error เมื่อลบไม่สำเร็จ

### 6. Authentication
- ทุกรายการ API ยกเว้นหน้า HTML ใช้ `verify_api_key` รองรับ 3 รูปแบบ:
  - `Authorization: Bearer <GATEWAY_API_KEY>`
  - `x-api-key: <GATEWAY_API_KEY>`
  - `?api_key=<GATEWAY_API_KEY>` (สำหรับ export/download ผ่านลิงก์)
- เปรียบเทียบแบบ constant-time (`hmac.compare_digest`) กัน timing attack

---

## ⚙️ การตั้งค่าและการใช้งาน (Configuration & Usage)

### Environment Variables (`app/config.py` + `.env.example`)
| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8830` | Service port |
| `GATEWAY_API_KEY` | `change-me-in-production` | Shared API key (ตั้งค่าจริงก่อนใช้งานจริง) |
| `MODEL_PATH` | `model/typhoon-asr-realtime.nemo` | Local model weights (fallback: HuggingFace) |
| `DEVICE` | `cuda` | `cuda` / `cpu` (auto-detect ถ้า CUDA ไม่พร้อม) |
| `LOG_LEVEL` | `info` | Logging level |
| `DATA_DIR` | `<service>/data` | SQLite directory |
| `TEMP_JOBS_DIR` | `/tmp/typhoon_jobs` | Temp job directory (ไฟล์ input/chunks) |
| `MIN_FREE_DISK_GB` | `5.0` | พื้นที่ดิสก์ขั้นต่ำก่อนรับ upload ใหม่ |
| `CLEANUP_RETENTION_HOURS` | `24` | อายุงานที่ periodic cleanup จัดการ |
| `MAX_CHUNK_DURATION_SEC` | `600` | ความยาว chunk สูงสุด (วินาที) |
| `CUDA_RETRY_ATTEMPTS` | `3` | จำนวนรอบ retry ต่อ chunk เมื่อเจอ transient CUDA error (Tier 1) |
| `CUDA_RETRY_BACKOFF_SEC` | `5` | ระยะเวลา backoff เริ่มต้น (คูณตามรอบ) ก่อน retry รอบถัดไป |
| `CUDA_RESET_ON_ALLOCATOR_ERROR` | `true` | เมื่อเจอ allocator corruption (`CUDACachingAllocator`) ทำ `cudaDeviceReset()` + reload โมเดล (Tier 2) |

### Database Schema (SQLite `jobs`)
| Column | Type | Description |
|---|---|---|
| `job_id` | TEXT PK | UUID ของงาน |
| `filename` | TEXT | ชื่อไฟล์ต้นฉบับ |
| `file_size_bytes` | INTEGER | ขนาดไฟล์อัปโหลด |
| `status` | TEXT | `queued/extracting/chunking/transcribing/completed/failed` |
| `progress_pct` | REAL | ความคืบหน้า % |
| `current_stage` | TEXT | Stage ปัจจุบัน (UI) |
| `total_chunks` / `completed_chunks` | INTEGER | ความคืบหน้าการ chunk |
| `duration_seconds` | REAL | ความยาวเสียง (วินาที) |
| `elapsed_seconds` | REAL | เวลาประมวลผลรวม |
| `result_text` | TEXT | ข้อความถอดความเต็ม |
| `timestamps_json` | TEXT | Word-level timestamps (JSON) |
| `srt_text` | TEXT | คำบรรยาย SRT |
| `error_message` | TEXT | ข้อผิดพลาด (ถ้ามี) |
| `created_at` / `updated_at` | TIMESTAMP | เวลาสร้าง/แก้ไข |

### API Surface
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | — | หน้าแรก / docs |
| GET | `/test/upload` | — | ทดสอบถอดความไฟล์เสียง |
| GET | `/test/realtime` | — | ทดสอบ real-time ไมค์ |
| GET | `/test/media` | — | ถอดความวิดีโอ/ไฟล์ยาว (1GB+) |
| GET | `/test/jobs` | — | **ประวัติการถอดความ (หน้าใหม่)** |
| GET | `/healthz` | — | Health check |
| POST | `/v1/transcribe` | ✅ | ถอดความไฟล์เสียง (bytes) |
| POST | `/v1/transcribe/jobs` | ✅ | สร้างงาน long-form (202, async) |
| GET | `/v1/transcribe/jobs` | ✅ | รายการงาน (`include_text`, `media_files_exist`) |
| GET | `/v1/transcribe/jobs/{job_id}` | ✅ | สถานะ + ผลลัพธ์ของงาน |
| DELETE | `/v1/transcribe/jobs/{job_id}` | ✅ | ลบทั้งแถว (record + media) |
| DELETE | `/v1/transcribe/jobs/{job_id}/media` | ✅ | **ลบเฉพาะไฟล์ media (เก็บ record)** |
| GET | `/v1/transcribe/jobs/{job_id}/export/{txt\|srt\|json}` | ✅ | Export ผลลัพธ์ |
| WS | `/v1/stream` | — | Real-time streaming |

### ตัวอย่างการใช้งาน (cURL)
```bash
# ถอดความไฟล์เสียงสั้น
curl -X POST http://localhost:8830/v1/transcribe \
  -H "x-api-key: change-me-in-production" \
  -F "file=@audio.mp3" -F "with_timestamps=true"

# สร้างงาน long-form (ได้ job_id ทันที)
curl -X POST http://localhost:8830/v1/transcribe/jobs \
  -H "x-api-key: change-me-in-production" \
  -F "file=@video.mp4"

# ตรวจสอบสถานะ
curl http://localhost:8830/v1/transcribe/jobs/<JOB_ID> \
  -H "x-api-key: change-me-in-production"

# รายการทั้งหมด (ไม่รวมข้อความเต็ม)
curl "http://localhost:8830/v1/transcribe/jobs?include_text=false" \
  -H "x-api-key: change-me-in-production"

# Export SRT
curl -o subtitle.srt "http://localhost:8830/v1/transcribe/jobs/<JOB_ID>/export/srt?api_key=change-me-in-production"

# ลบเฉพาะไฟล์ media (เก็บข้อมูลถอดความ)
curl -X DELETE http://localhost:8830/v1/transcribe/jobs/<JOB_ID>/media \
  -H "x-api-key: change-me-in-production"

# ลบทั้งแถว
curl -X DELETE http://localhost:8830/v1/transcribe/jobs/<JOB_ID> \
  -H "x-api-key: change-me-in-production"
```

### WebSocket (JavaScript)
```javascript
const ws = new WebSocket(`ws://localhost:8830/v1/stream`);
// ส่ง audio chunk bytes + คำสั่ง text: "INTERIM" (partial), "COMMIT_SEGMENT" (final), "CLEAR"
ws.send(audioBlob);
ws.send("COMMIT_SEGMENT");
```

---

## 🐳 Docker & การรัน (Docker & Deployment)

### Local Development
```bash
# GPU (ต้องมี CUDA)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
```

### Docker (ผ่าน compose ของโปรเจค ChooNova AI)
```bash
docker compose up -d --build typhoon-asr-service   # GPU (docker-compose.yml)
docker compose -f docker-compose-cpu.yml up -d --build typhoon-asr-service
docker compose logs -f typhoon-asr-service
```
- **Image**: `choonova-typhoon-asr:latest` (GPU) / `:cpu` — model ดาวน์โหลดตอน build (HF cache ใน image)
- **Port**: `8830:8830`
- **Volume**: `./services/typhoon-asr-service/data:/app/data` (SQLite อยู่ได้ข้าม container)
- **GPU**: NVIDIA device reservation (`driver: nvidia, capabilities: [gpu]`)
- **Healthcheck**: `curl -f http://127.0.0.1:8830/healthz` (30s interval)
- **Network**: `km4u-network` (ต้องสร้างก่อน: `docker network create km4u-network`)

> Dockerfiles ใช้ multi-stage ง่ายๆ: apt install `ffmpeg libsndfile1 curl git build-essential` → pip install → ดาวน์โหลด `.nemo` ลง `/app/model` → COPY `app/` → CMD uvicorn

---

## 🧪 การทดสอบระบบ (Testing)

- บริการนี้ยังไม่มี test runner / test script อย่างเป็นทางการ
- **Manual verification** ผ่าน dashboard: `http://localhost:8830/` (หน้า upload / realtime / media / jobs)
- **API verification** ด้วย cURL ตามตัวอย่างด้านบน หรือผ่านหน้า `/test/jobs` (รายการ + export + ลบ)
- โครงสร้างเบื้องต้นสามารถตรวจสอบด้วย:
  ```bash
  python -m py_compile app/main.py app/db.py app/config.py app/audio_utils.py
  node --check app/static/js/jobs.js
  ```
- ในอดีตใช้ FastAPI `TestClient` (พ่น stub `asr_engine`) ตรวจสอบ list / delete media / delete row / cleanup retention ได้ครบ

---

## 📅 สถานะการพัฒนาและแผนงาน (Development Status & Roadmap)

- [x] **Phase 1: REST API** — `POST /v1/transcribe` (multipart, with_timestamps)
- [x] **Phase 2: WebSocket Real-time** — `/v1/stream` (partial/final, overlap removal)
- [x] **Phase 3: Long-form Video Pipeline** — async job (202), FFmpeg extract, silence chunking, GPU lock, SRT/export
- [x] **Phase 4: Dashboard** — หน้า Home, upload tester, realtime mic tester, media uploader (1GB+)
- [x] **Phase 5: ประวัติการถอดความ** — หน้า `/test/jobs`, ลบเฉพาะ media (`DELETE /{id}/media`), list lean (`include_text`, `media_files_exist`), cleanup เก็บ record งาน completed
- [ ] ปรับปรุง: เพิ่ม test runner อย่างเป็นทางการ (pytest + TestClient), ปรับ `MAX_CHUNK_DURATION_SEC` ให้ config จริงใน pipeline, รองรับการถอดความไฟล์ `.docx/.pdf` ผ่าน pipeline
