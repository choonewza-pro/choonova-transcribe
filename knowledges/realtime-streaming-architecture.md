# Realtime Streaming Transcription - Architecture & Data Flow

## Overview

หน้า `/realtime/stream` คือฟีเจอร์แปลเสียงพูดแบบเรียลไทม์ผ่านไมโครโฟน โดยใช้ WebSocket ส่งเสียงจากเบราว์เซอร์ไปยังเซิร์ฟเวอร์ แล้วส่งผลลัพธ์ข้อความกลับมาแสดงผลทันที

---

## End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Browser)                          │
│                                                                     │
│  [Mic] → [MediaRecorder] ──(WebM/Opus 250ms)──→ [WebSocket]       │
│                │                                       ↑            │
│         [Web Audio VAD]                                │            │
│    (RMS ≥ 0.015 + timers)                              │            │
│         │         │                                    │            │
│    "INTERIM"  "COMMIT_SEGMENT"  ───────────────────────→            │
│     (1s poll)  (600ms silence                          │            │
│                 or 10s speech)        ←── JSON Response │            │
│                                    {"type":"partial"    │            │
│                                     "text":"..."        │            │
│                                     "fullText":"..."}   │            │
└─────────────────────────────────────────────────────────────────────┘
                              │                    ↑
                              ▼                    │
┌─────────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI Server)                        │
│                                                                     │
│  WebSocket /v1/realtime/stream                                     │
│       │                                                             │
│       ▼                                                             │
│  [io.BytesIO Buffer] ← accumulate WebM chunks                     │
│       │                                                             │
│       │  (triggered by INTERIM / COMMIT_SEGMENT)                   │
│       ▼                                                             │
│  [ffmpeg In-Memory Pipe]  WebM/Opus → WAV 16kHz (pipe:0 → pipe:1)   │
│       │                                                             │
│       ▼                                                             │
│  [engine.transcribe_bytes(wav_data, "stream.wav")]                 │
│       │                                                             │
│       ▼                                                             │
│  [soundfile.read (fast-path) → bypass duplicate disk write]        │
│       │                                                             │
│       ▼                                                             │
│  [NeMo Typhoon ASR model.transcribe()]  (GPU inference)            │
│       │                                                             │
│       ▼                                                             │
│  [remove_text_overlap()] → WebSocket JSON response                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Files & Responsibilities

### Frontend

| File | Role |
|------|------|
| `app/templates/realtime.html` | Jinja2 HTML template - UI layout |
| `app/static/js/realtime.js` | Mic capture, VAD, MediaRecorder, WebSocket client |
| `app/static/js/model_status.js` | VRAM status badge polling, model loading dialog |

### Backend

| File | Role |
|------|------|
| `app/api/v1/realtime_router.py` | WebSocket endpoint, buffer management, ffmpeg conversion |
| `app/asr_engine.py` | Typhoon ASR model singleton (load, transcribe, CUDA) |
| `app/engine_router.py` | Language routing (th→Typhoon, en→Whisper), multi-engine CUDA reset |

---

## Step-by-Step Flow

### Step 1: User เปิดหน้า Realtime

```
GET /realtime/stream → realtime.html
                        ├── style.css
                        ├── model_status.js  (เริ่ม poll /healthz ทุก 3s)
                        └── realtime.js      (เตรียม UI, เช็ค mic permission)
```

`model_status.js` เริ่ม poll `/healthz` ทุก 3 วินาที เพื่อแสดงสถานะ VRAM badge:
- `🟢 พร้อม` (loaded)
- `🟡 กำลังโหลด` (loading)
- `⚪ idle` (idle)

### Step 2: User กดปุ่ม Mic

`realtime.js` → `startRecording()`:

1. **ขอสิทธิ์ไมค์**: `navigator.mediaDevices.getUserMedia({ audio: ... })`
2. **สร้าง Web Audio Visualizer**: `AudioContext` → `AnalyserNode` → canvas animation
3. **เช็ค Model Status**: ถ้าโมเดลยังไม่ loaded → แสดง dialog "กำลังโหลดโมเดล..."
4. **เปิด WebSocket**: `ws://<host>/v1/realtime/stream`

### Step 3: WebSocket Connected (socket.onopen)

Frontend:
```javascript
socket.send('CLEAR');                    // ล้าง session ก่อนหน้า
mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
mediaRecorder.start(250);               // ส่ง binary chunk ทุก 250ms
interimTimer = setInterval(() => {
    if (hasSpeechSinceLastCommit) {
        socket.send('INTERIM');          // ขอผลลัพธ์ระหว่างพูด ทุก 600ms
    }
}, 600);
```

Backend (`realtime_router.py`):
```python
engine = get_asr_engine()
asyncio.get_event_loop().run_in_executor(None, engine.load_model)  # warmup ทันที
```

### Step 4: Audio Streaming Loop

**Frontend (ทุก 250ms):**
```
MediaRecorder.ondataavailable → socket.send(event.data)  # binary WebM chunk
```

**Backend (receive loop):**
```python
while True:
    msg = await websocket.receive()
    if "bytes" in msg:
        chunk = msg["bytes"]
        if not header_bytes:
            header_bytes = chunk[:1024]   # เก็บ WebM container header
        audio_buffer.write(chunk)         # สะสมใน BytesIO buffer
```

### Step 5: Voice Activity Detection (VAD)

Frontend `realtime.js` ใช้ Web Audio API ตรวจจับเสียงพูดแบบ client-side:

```
AnalyserNode.getFloatTimeDomainData(buffer)
RMS = sqrt(sum(sample²) / N)
```

| Condition | Action |
|-----------|--------|
| `RMS ≥ 0.015` (กำลังพูด) | `hasSpeechSinceLastCommit = true` |
| พูดต่อเนื่อง > 10s | ส่ง `COMMIT_SEGMENT` (force) |
| เงียบ > 600ms หลังพูด | ส่ง `COMMIT_SEGMENT` (silence boundary) |
| กำลังพูด + ครบ 600ms interval | ส่ง `INTERIM` (ขอผลลัพธ์ระหว่างพูด) |

### Step 6: Server รับคำสั่ง INTERIM / COMMIT_SEGMENT

```python
elif "text" in msg:
    cmd = msg["text"].strip()  # "INTERIM" / "COMMIT_SEGMENT" / "CLEAR"
```

**ทั้ง INTERIM และ COMMIT_SEGMENT** ทำงานคล้ายกัน:

1. ดึง `b_data = audio_buffer.getvalue()` (ข้อมูล WebM ทั้งหมดที่สะสมไว้)
2. เรียก `_transcribe_bytes_async(b_data)`
3. ส่งผลลัพธ์กลับทาง WebSocket

**ความแตกต่าง:**

| | INTERIM | COMMIT_SEGMENT |
|---|---------|----------------|
| Response type | `"partial"` | `"final"` |
| ล้าง buffer | ❌ ไม่ล้าง | ✅ ล้าง (เริ่ม buffer ใหม่) |
| อัพเดท finalized_text | ❌ | ✅ |
| ข้าม ถ้า lock ถูกถือ | ✅ | ❌ (รอ lock) |

### Step 7: WebM → WAV In-Memory Conversion (FFmpeg Pipes)

**ทำไมต้องแปลงใน RAM?**
- เบราว์เซอร์ MediaRecorder ส่งเสียงเป็น **WebM/Opus** format
- `libsndfile` (backend ของ soundfile/librosa) **ไม่รองรับ WebM**
- แปลงผ่าน **FFmpeg In-Memory Pipes (`pipe:0` -> `pipe:1`)** โดยไม่ต้องเขียน/อ่านดิสก์ ทำให้ประมวลผลได้รวดเร็วใน RAM

```python
def _convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    # Transcode WebM/Opus -> WAV 16kHz mono in RAM via stdin/stdout pipes
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
        input=webm_bytes, capture_output=True, timeout=5
    )
    return result.stdout
```

### Step 7.1: Sliding Window Preview สำหรับ INTERIM
คำสั่ง `INTERIM` จะตัดส่งเฉพาะช่วงเสียงย้อนหลัง **~4-5 วินาทีล่าสุด** (`b_data[-120000:]` + `header_bytes`) ไปประมวลผล ทำให้ GPU ถอดความได้รวดเร็ว (< 50ms) เสมอไม่ว่าจะพูดต่อเนื่องนานแค่ไหน

Parameters:
- `-ar 16000` → resample เป็น 16kHz mono PCM (ตรงตามข้อกำหนดของโมเดล)
- `pipe:0` / `pipe:1` → stdin / stdout in-memory stream (Zero Disk Write)

### Step 8: ASR Engine Transcription (Fast-Path)

```python
engine.transcribe_bytes(wav_data, "stream.wav")
    └── transcribe_file(tmp_path)
        ├── prepare_audio(audio_path, target_sr=16000)
        │   ├── soundfile.read(path)             # fast-path (~100x faster than librosa)
        │   └── if sr == 16000: return path      # bypass duplicate disk write!
        │
        └── model.transcribe([path])             # NeMo inference (GPU)
            └── torch.cuda.synchronize()        # catch deferred CUDA errors
```

โมเดล: **SCB-10X Typhoon ASR Realtime** (FastConformer-Transducer, 114M params, ~1GB VRAM FP16)

### Step 9: Text Overlap Deduplication

เนื่องจาก streaming ส่งเสียงที่ซ้อนทับกัน (buffer สะสมต่อเนื่อง) ข้อความที่แปลได้อาจมีคำซ้ำ:

```python
def remove_text_overlap(t1: str, t2: str) -> str:
    # t1 = "สวัสดีครับวันนี้"     (finalized text)
    # t2 = "วันนี้อากาศดี"        (new transcription)
    # result = "สวัสดีครับวันนี้ อากาศดี"  (ตัด "วันนี้" ซ้ำออก)
```

ตรวจสอบ suffix ของ t1 ที่ตรงกับ prefix ของ t2 (สูงสุด 60 ตัวอักษร)

### Step 10: WebSocket Response → UI Update

**Server ส่ง:**
```json
{"type": "partial", "text": "สวัสดี", "fullText": "สวัสดี"}
{"type": "final",   "text": "สวัสดีครับ", "fullText": "สวัสดีครับ"}
```

**Frontend รับ (`socket.onmessage`):**
```javascript
if (data.type === 'final') {
    confirmedText = data.fullText;
    liveTranscript.innerHTML = confirmedText;
} else if (data.type === 'partial') {
    liveTranscript.innerHTML = confirmedText +
        ' <span class="partial-text">' + data.text + '</span>';
}
```

- `final` → ข้อความที่ยืนยันแล้ว (สีปกติ)
- `partial` → ข้อความกำลังประมวลผล (สี muted, italic)

---

## Key Constants & Thresholds

### Frontend (`realtime.js`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `SILENCE_THRESHOLD` | `0.015` | RMS energy ต่ำกว่านี้ถือว่าเงียบ |
| `SILENCE_DURATION_MS` | `600` | เงียบ 600ms → trigger COMMIT |
| `MAX_SEGMENT_DURATION` | `10000` | พูดต่อเนื่อง 10s → force COMMIT |
| `MediaRecorder.start()` | `250` | ส่ง audio chunk ทุก 250ms |
| `interimTimer interval` | `1000` | ส่ง INTERIM ทุก 1s (ถ้ากำลังพูด) |

### Backend (`realtime_router.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_BUFFER_BYTES` | `480000` | จำกัดขนาด buffer (~15s WebM) |
| Min audio size | `4096` | ข้อมูลเสียงต่ำกว่านี้ไม่แปล |
| `CUDA_RETRY_ATTEMPTS` | `2` | จำนวนครั้ง retry เมื่อ CUDA error |
| ffmpeg timeout | `15s` | timeout สำหรับ conversion |

### ASR Engine (`asr_engine.py`)

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Target sample rate | `16000 Hz` | ความถี่สุ่มตัวอย่างที่โมเดลรับ |
| Peak normalization | `y / (max + 1e-8)` | ปรับระดับเสียงให้สม่ำเสมอ |
| Max chunk duration | `60s` | เสียงยาวกว่านี้จะถูก auto-chunk |
| Target chunk duration | `30s` | ขนาด chunk เป้าหมายที่ตัด |

---

## WebSocket Commands Protocol

```
Client → Server (Text frames):
┌──────────────────┬──────────────────────────────────────────────┐
│ Command          │ Purpose                                      │
├──────────────────┼──────────────────────────────────────────────┤
│ "CLEAR"          │ ล้าง buffer + finalized_text ทั้งหมด        │
│ "INTERIM"        │ ขอผลลัพธ์ interim (ไม่ล้าง buffer)          │
│ "COMMIT_SEGMENT" │ ยืนยัน segment (ล้าง buffer, อัพเดท text)   │
└──────────────────┴──────────────────────────────────────────────┘

Client → Server (Binary frames):
┌──────────────────────────────────────────────────────────────────┐
│ WebM/Opus audio chunks (every 250ms from MediaRecorder)         │
└──────────────────────────────────────────────────────────────────┘

Server → Client (JSON text frames):
┌──────────┬───────────────────────────────────────────────────────┐
│ type     │ Fields                                                │
├──────────┼───────────────────────────────────────────────────────┤
│ "partial"│ text (segment), fullText (accumulated preview)        │
│ "final"  │ text (segment), fullText (accumulated confirmed)      │
└──────────┴───────────────────────────────────────────────────────┘
```

---

## CUDA Error Recovery Strategy

```
Transient CUDA Error
    │
    ├── Attempt 1: clear_cuda_cache() → retry
    │
    ├── Attempt 2: reset_all() + clear_cuda_cache() → retry
    │
    └── Allocator Corruption (INTERNAL ASSERT FAILED):
            cuda_device_reset_all()  → model reload → retry
```

| Recovery Level | Function | What it does |
|----------------|----------|--------------|
| Light | `clear_cuda_cache()` | `gc.collect()` + `torch.cuda.synchronize()` |
| Medium | `reset_all()` | Drop model reference, `_is_loaded = False` |
| Heavy | `cuda_device_reset_all()` | `cudaDeviceReset()` → rebuild CUDA context → reload model |

> **Note:** `torch.cuda.empty_cache()` ต้อง **ไม่เรียก** ระหว่าง consecutive `model.transcribe()` เพราะ NeMo FastConformer ใช้ CUDA graphs ที่ยังอ้างอิง memory อยู่ (NeMo issue #14727)

---

## Model Loading & Warmup

### Warmup-on-Connect

เมื่อ WebSocket เชื่อมต่อ, server จะเรียก `engine.load_model()` ทันทีใน background thread:

```python
asyncio.get_event_loop().run_in_executor(None, engine.load_model)
```

**ทำไมต้อง warmup?**
หากไม่ warmup จะเกิด deadlock:
- Frontend แสดง dialog "กำลังโหลดโมเดล..." → user รอ dialog หาย
- Server รอเสียงพูด (INTERIM) ก่อนถึงจะโหลดโมเดล (lazy load)
- ทั้งสองฝ่ายรอกันไปมาไม่มีที่สิ้นสุด

### Model Status Polling

`model_status.js` poll `/healthz` ทุก 3s (ปกติ) หรือ 1-2s (ขณะ dialog เปิดอยู่):

```
/healthz → { typhoon_model_state: "loaded" | "loading" | "idle",
             whisper_model_state: "...",
             model_load_mode: "always" | "idle" }
```

เมื่อ `typhoon_model_state === "loaded"` → dialog หาย → user เริ่มพูดได้

---

## Audio Buffer Management

```
audio_buffer (io.BytesIO)
┌─────────────────────────────────────────────────────┐
│ header_bytes (1024B) │ chunk1 │ chunk2 │ ... │ chunkN │
└─────────────────────────────────────────────────────┘
       ↑ WebM container header (เก็บไว้ตลอด session)

เมื่อ buffer > MAX_BUFFER_BYTES (480KB):
    → เก็บเฉพาะ header + 480KB สุดท้าย (ตัดส่วนเก่าทิ้ง)

เมื่อ COMMIT_SEGMENT:
    → b_data = buffer.getvalue()   (ดึงออกมาแปล)
    → buffer = new BytesIO()       (เริ่มใหม่)
    → buffer.write(header_bytes)   (ใส่ header กลับ)
```

**ทำไมต้องเก็บ header_bytes?**
WebM container format ต้องมี header (metadata เกี่ยวกับ codec, sample rate) อยู่ที่ต้นไฟล์เสมอ ถ้าไม่มี header, ffmpeg จะไม่สามารถ decode ข้อมูลที่เหลือได้

---

## Lessons Learned (Bug Fix History)

### LibsndfileError: Format not recognised

**อาการ:** หน้า Realtime เปิด WebSocket สำเร็จ, model โหลดขึ้น VRAM สำเร็จ, แต่ไม่มีข้อความปรากฏเลย และไม่มี error log ใดๆ

**Root Cause:** `librosa.load()` ใช้ `libsndfile` ซึ่งไม่รองรับ WebM container format → ทุกครั้งที่พยายามแปลเสียงจะ throw `LibsndfileError` → error ถูก catch แล้ว log ที่ระดับ `DEBUG` (มองไม่เห็นที่ log level `INFO`)

**Fix:** เพิ่ม `_convert_webm_to_wav()` ใช้ ffmpeg แปลง WebM→WAV ก่อนส่งให้โมเดล + ยกระดับ error log จาก `debug` เป็น `warning`

**บทเรียน:** อย่าใช้ `logger.debug()` สำหรับ error ใน critical path — ใช้ `logger.warning()` เป็นอย่างน้อย
