# Implementation Plan: Speaker Diarization Pipeline (v2)

> **ChooNova Transcribe: Audio Transcription & Speaker Diarization Pipeline (4 Pathways Architecture)**  
> สถานะ: **PLAN v2** — รองรับ Typhoon + PyAnnote 3.1 สำหรับภาษาไทย และ WhisperX สำหรับภาษาอังกฤษ/Auto

## 0. Git Branch Strategy

สร้างและสลับไปยัง Git branch ใหม่ก่อนเริ่มการพัฒนา:

```bash
rtk git checkout -b feat/speaker-diarization-pipeline
```

---

## 1. Architectural Overview (4 Pathways Matrix)

ระบบแบ่งเส้นทางการถอดความออกเป็น **4 เส้นทาง (4 Pathways)** ตามการเลือกภาษาและโหมดระบุผู้พูด:

```
                                ┌───────────────────────────┐
                                │   Transcribe Request      │
                                └─────────────┬─────────────┘
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
           enable_diarization = FALSE                    enable_diarization = TRUE
                       │                                             │
             ┌─────────┴─────────┐                         ┌─────────┴─────────┐
             ▼                   ▼                         ▼                   ▼
       [ Thai / th ]       [ Eng / Auto ]            [ Thai / th ]       [ Eng / Auto ]
             │                   │                         │                   │
             ▼                   ▼                         ▼                   ▼
        Typhoon ASR        Faster-Whisper             Typhoon ASR           WhisperX
      (FastConformer)     (large-v3-turbo)                 +          (ASR + Alignment
                                                     PyAnnote 3.1       + PyAnnote Diarize)
                                                     (Max-Overlap)
```

### 1.1 ตารางเปรียบเทียบกลไกการทำงาน

| Pathway | ภาษา | โหมดระบุผู้พูด | Engine Pipeline | เหตุผล & กลไก |
|---|---|---|---|---|
| **Path 1** | `th` | ❌ ปิด | **Typhoon ASR** | FastConformer-Transducer 114M ถอดความภาษาไทยเร็วและแม่นยำที่สุด (~1GB VRAM) |
| **Path 2** | `en` / `auto` | ❌ ปิด | **Faster-Whisper** | CTranslate2 `large-v3-turbo` ถอดความภาษาอังกฤษและตรวจจับภาษาอัตโนมัติ (~3.5GB VRAM) |
| **Path 3** | `th` | ✅ เปิด | **Typhoon ASR + PyAnnote 3.1** | ถอดความด้วย Typhoon $\rightarrow$ สกัดช่วงเวลาผู้พูดด้วย PyAnnote $\rightarrow$ รวมผลลัพธ์ด้วย **Maximum-Overlap Algorithm** (เนื่องจาก WhisperX ไม่มี forced alignment model สำหรับภาษาไทย) |
| **Path 4** | `en` / `auto` | ✅ เปิด | **WhisperX** | Transcribe $\rightarrow$ Phoneme-level Forced Alignment (wav2vec2) $\rightarrow$ PyAnnote Diarization $\rightarrow$ Assign Word Speakers (ให้ความแม่นยำระดับคำสูงสุดสำหรับภาษาอังกฤษ) |

### 1.2 ขอบเขตการทำงาน (Scope)
- ✅ **Long-form Async Jobs (`POST /v1/media/transcribe/jobs`):** รันใน Isolated Worker Subprocess (`python -m app.run_job`) ป้องกัน VRAM รั่วไหลใน Main Process
- ✅ **Short-form Sync (`POST /v1/audio/transcribe`):** รัน in-process ใน Worker Thread พร้อมระบบเคลียร์ VRAM อัตโนมัติหลังทำงานเสร็จ
- ❌ **Realtime WebSocket (`/v1/realtime/stream`):** คงเป็น Typhoon ASR ล้วน ไม่เปิด Diarization เพื่อรักษา Latency ต่ำสุด (~0.5s)

---

## 2. Dependencies & Environment

### 2.1 `requirements.txt` (GPU)
```text
--extra-index-url https://download.pytorch.org/whl/cu121
torch==2.5.1
torchaudio==2.5.1
...
faster-whisper==1.2.1
pyannote.audio==3.1.1
git+https://github.com/m-bain/whisperX.git
```

### 2.2 `requirements-cpu.txt` (CPU)
```text
torch==2.5.1
torchaudio==2.5.1
...
faster-whisper==1.2.1
pyannote.audio==3.1.1
git+https://github.com/m-bain/whisperX.git
```

### 2.3 `.env.example`
```bash
# ===== HuggingFace & Speaker Diarization =====
# จำเป็นสำหรับ PyAnnote 3.1 และ WhisperX (ต้องยอมรับ Gated License บน HF)
# 1. https://hf.co/pyannote/speaker-diarization-3.1
# 2. https://hf.co/pyannote/segmentation-3.0
HF_TOKEN=

DIARIZATION_ENABLED=true
DIARIZATION_MODEL=pyannote/speaker-diarization-3.1
DIARIZATION_MIN_SPEAKERS=
DIARIZATION_MAX_SPEAKERS=
```

---

## 3. Configuration (`app/core/config.py`)

เพิ่มการตั้งค่าสำหรับ Diarization ต่อจาก `HF_TOKEN`:

```python
# Speaker Diarization (PyAnnote 3.1 & WhisperX)
DIARIZATION_ENABLED = os.getenv("DIARIZATION_ENABLED", "true").lower() in ("true", "1", "yes")
DIARIZATION_MODEL = os.getenv("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
DIARIZATION_MIN_SPEAKERS = int(os.getenv("DIARIZATION_MIN_SPEAKERS", "") or 0) or None
DIARIZATION_MAX_SPEAKERS = int(os.getenv("DIARIZATION_MAX_SPEAKERS", "") or 0) or None
```

---

## 4. New Adapters & Engine Implementations

### 4.1 `app/pyannote_engine.py` (สำหรับ Path 3: Thai + Diarization)
โมดูลสำหรับจัดการ PyAnnote Diarization แยกเฉพาะภาษาไทย:

```python
class PyAnnoteDiarizer:
    """
    Adapter สำหรับ PyAnnote 3.1 Diarization Pipeline
    รองรับ Lazy Loading, GPU memory management และ Idle timeout
    """
    def __init__(self, model_name: str, device: str): ...
    def load_model(self) -> None: ...  # Lazy import pyannote.audio และตรวจจับ HF_TOKEN
    def diarize(self, audio_path: str, min_speakers=None, max_speakers=None) -> List[Dict[str, Any]]: ...
    def unload_model(self) -> None: ... # del pipeline + gc.collect() + clear_cuda_cache()
    def unload_if_idle(self, timeout_sec: float) -> bool: ...

# Optimized Pure Functions (Testable โดยไม่ต้องต่อ GPU)
def merge_speaker_overlap(segments: List[Dict[str, Any]], diarization_turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    จับคู่คำ/ท่อนเสียง (segments) กับช่วงเวลาผู้พูด (diarization_turns) ด้วย Maximum Overlap Algorithm
    พร้อมระบบ Nearest-neighbor Fallback ป้องกันคำหลุดเป็น UNKNOWN ในช่วง pause
    """

def group_speaker_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    รวมคำที่ต่อเนื่องกันและเป็นผู้พูดคนเดียวกันเข้าเป็นท่อนประโยค (Speaker Turn Segments)
    """

def diarize_audio(audio_path: str, min_speakers=None, max_speakers=None) -> List[Dict[str, Any]]: ...
```

#### กลไก Maximum Overlap ที่ปรับปรุงประสิทธิภาพ (Optimized):
```python
def merge_speaker_overlap(segments, diarization_turns, gap_tolerance_sec=0.5):
    # 1. แปลง turns เป็น list รอบเดียวก่อนลูป
    # 2. วนลูปคำนวณ overlap
    for seg in segments:
        t_start, t_end = seg["start"], seg["end"]
        best_speaker, max_overlap = "UNKNOWN", 0.0
        for turn in diarization_turns:
            overlap = max(0.0, min(t_end, turn["end"]) - max(t_start, turn["start"]))
            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = turn["speaker"]
        
        # Fallback: ถ้าตกในช่วงช่องว่างสั้นๆ ให้หา turn ที่ใกล้ที่สุด
        if max_overlap == 0.0 and diarization_turns:
            closest_turn = min(diarization_turns, key=lambda t: min(abs(t["start"] - t_end), abs(t["end"] - t_start)))
            dist = min(abs(closest_turn["start"] - t_end), abs(closest_turn["end"] - t_start))
            if dist <= gap_tolerance_sec:
                best_speaker = closest_turn["speaker"]

        seg["speaker"] = best_speaker
    return segments
```

---

### 4.2 `app/whisperx_engine.py` (สำหรับ Path 4: Eng/Auto + Diarization)
โมดูลสำหรับจัดการ WhisperX Pipeline:

```python
class WhisperXDiarizer:
    """
    Adapter สำหรับ WhisperX (ASR + Forced Alignment + Diarization)
    """
    def __init__(self, model_name: str, device: str, compute_type: str): ...
    def load_model(self) -> None: ...  # Lazy import whisperx
    def transcribe_and_diarize(
        self,
        audio_path: str,
        language: Optional[str] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        1. whisperx.load_audio(audio_path)
        2. asr_model.transcribe(audio, batch_size=16, language=language)
        3. Try Forced Alignment:
           try:
               model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=self.device)
               result = whisperx.align(result["segments"], model_a, metadata, audio, self.device)
           except Exception as e:
               logger.warning(f"Alignment skipped (unsupported language or fallback): {e}")
        4. Diarization:
           diarize_model = whisperx.DiarizationPipeline(model_name=DIARIZATION_MODEL, use_auth_token=HF_TOKEN, device=self.device)
           diarize_segments = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
        5. Assign Word Speakers:
           result = whisperx.assign_word_speakers(diarize_segments, result)
        6. Return standardized dict: {"text": ..., "segments": [...]}
        """
    def unload_model(self) -> None: ...
```

---

## 5. Long-Form Async Job Pipeline

### 5.1 Database Schema Migration (`app/db.py`)
- เพิ่มคอลัมน์ `enable_diarization INTEGER DEFAULT 0` ใน `CREATE TABLE jobs`
- เพิ่ม Auto-migration ผ่าน `PRAGMA table_info(jobs)` เพื่อรองรับฐานข้อมูลเดิม
- ปรับ `create_job()` ให้รับ `enable_diarization: bool = False`

### 5.2 Hexagonal Domain & Repository
- **Entity (`app/modules/transcription/domain/entities.py`):**
  เพิ่ม `enable_diarization: bool = False` ใน `TranscriptionJob`
- **Repository (`app/modules/transcription/adapters/outbound/repositories/sqlite_job_repository.py`):**
  เพิ่มการอ่านและบันทึกคอลัมน์ `enable_diarization` ใน `_row_to_job()` และ `create_job()`
- **Service (`app/modules/transcription/application/transcription_service.py`):**
  เพิ่มพารามิเตอร์ `enable_diarization` ใน `create_job()`

### 5.3 Dispatcher & Worker Subprocess
- **Dispatcher (`app/main.py`):**
  ส่งอาร์กิวเมนต์ที่ 4 เมื่อสั่งรัน Subprocess:
  ```python
  cmd = [sys.executable, "-m", "app.run_job", job_id, save_path, lang, str(int(bool(job.get("enable_diarization"))))]
  ```
- **Inbound Worker (`app/modules/transcription/adapters/inbound/workers/run_job.py` & `app/run_job.py`):**
  รับและส่งต่อ `enable_diarization: bool` เข้า `process_transcription_job()`

### 5.4 Worker Execution Flow (`app/job_worker.py`)
ลำดับการทำงานใน Background Worker:

```text
1. Extract Audio (MP4 -> 16kHz WAV)
2. If enable_diarization == False:
   - Run Path 1 (Typhoon) หรือ Path 2 (Faster-Whisper) ผ่าน Silence-Aware Chunking (เหมือนเดิม 100%)
3. If enable_diarization == True:
   a. If language == "th" (Path 3):
      - Run Silence-Aware Chunking + Typhoon ASR
      - Update stage="diarizing", progress=90%
      - Call engine.reset() เพื่อคืน VRAM ของ Typhoon
      - Run pyannote.diarize(extracted_wav)
      - Run merge_speaker_overlap + group_speaker_segments
   b. If language in ("en", "auto") (Path 4):
      - Update stage="transcribing_diarizing", progress=30%
      - Run whisperx_engine.transcribe_and_diarize(extracted_wav, language=lang)
4. Build Output Data:
   - Format segments พร้อมระบุ speaker: "SPEAKER_00", "SPEAKER_01"
   - Format full text พร้อมแบ่งบรรทัดตามผู้พูด: "[SPEAKER_00]: สวัสดีครับ\n[SPEAKER_01]: ยินดีครับ"
   - Build SRT Subtitles พร้อมใส่ speaker tag
5. Cleanup & Save Database Result
```

---

## 6. Short-Form Sync Endpoint (`app/api/v1/transcription_router.py`)

ปรับปรุง `POST /v1/audio/transcribe`:
```python
@router.post("/v1/audio/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    with_timestamps: bool = Form(False),
    language: str = Form("th"),
    enable_diarization: bool = Form(False),
    authenticated: bool = Depends(verify_api_key),
):
    # 1. Validation & Save temporary audio file
    # 2. If not enable_diarization:
    #    - ใช้ router_transcribe_bytes (Path 1 / Path 2 เดิม)
    # 3. If enable_diarization:
    #    - If lang == "th": Typhoon transcribe + PyAnnote diarize + merge_speaker_overlap
    #    - Else: WhisperX transcribe_and_diarize
    # 4. Immediate VRAM cleanup if MODEL_LOAD_MODE == "idle"
    # 5. Return TranscribeResponse พร้อม timestamps และ speaker
```

---

---

## 7. Storage & Response Contract (การบันทึกข้อมูลและการตอบกลับ API)

ระบบเดิมได้รับการออกแบบให้รองรับการขยายฟิลด์ผ่าน JSON Serialization ไว้อยู่แล้ว จึง **ไม่มี Breaking Changes (100% Backward-Compatible)**:

### 7.1 SQLite Storage (`jobs` table)
- คอลัมน์ `result_json TEXT` เก็บ JSON String ของผลลัพธ์:
  - **เมื่อปิด Diarization (เดิม):**
    ```json
    {
      "text": "สวัสดีครับ วันนี้เรามาทดสอบระบบ",
      "segments": [
        {"text": "สวัสดีครับ", "start": 0.0, "end": 1.2},
        {"text": "วันนี้เรามาทดสอบระบบ", "start": 1.3, "end": 3.5}
      ]
    }
    ```
  - **เมื่อเปิด Diarization (ใหม่):**
    ```json
    {
      "text": "[SPEAKER_00]: สวัสดีครับ\n[SPEAKER_01]: วันนี้เรามาทดสอบระบบ",
      "segments": [
        {"text": "สวัสดีครับ", "start": 0.0, "end": 1.2, "speaker": "SPEAKER_00"},
        {"text": "วันนี้เรามาทดสอบระบบ", "start": 1.3, "end": 3.5, "speaker": "SPEAKER_01"}
      ]
    }
    ```

### 7.2 API Response Models (`app/schemas.py`)
- `TimestampItem` (สำหรับ Short-form): เพิ่ม `speaker: Optional[str] = None`
- `TranscriptionSegment` (สำหรับ Long-form): เพิ่ม `speaker: Optional[str] = None`
- `JobStatusResponse`: เพิ่ม `enable_diarization: bool = False`
- `JobCreateResponse`: เพิ่ม `enable_diarization: bool = False`
- `JobStage`: เพิ่ม `diarizing = "diarizing"`

#### ตัวอย่าง Response: Short-form (`POST /v1/audio/transcribe`)
```json
{
  "status": "success",
  "text": "สวัสดีครับ ยินดีต้อนรับ",
  "duration_seconds": 3.2,
  "elapsed_seconds": 0.45,
  "rtf": 0.14,
  "timestamps": [
    {"word": "สวัสดีครับ", "start": 0.0, "end": 1.1, "speaker": "SPEAKER_00"},
    {"word": "ยินดีต้อนรับ", "start": 1.2, "end": 2.8, "speaker": "SPEAKER_00"}
  ]
}
```

#### ตัวอย่าง Response: Long-form (`GET /v1/media/transcribe/jobs/{job_id}`)
```json
{
  "id": "c7a8b9e0-1234-5678-abcd-ef0123456789",
  "status": "completed",
  "stage": "completed",
  "progress": 100.0,
  "enable_diarization": true,
  "result": {
    "text": "[SPEAKER_00]: สวัสดีครับ\n[SPEAKER_01]: ยินดีที่ได้คุยกันครับ",
    "segments": [
      {
        "text": "สวัสดีครับ",
        "start": 0.0,
        "end": 1.5,
        "speaker": "SPEAKER_00"
      },
      {
        "text": "ยินดีที่ได้คุยกันครับ",
        "start": 1.8,
        "end": 3.4,
        "speaker": "SPEAKER_01"
      }
    ]
  }
}
```

### 7.3 Export Endpoints
- **`GET /export/txt`:** คืน Plain text โดยถ้าเปิด Diarization จะมี prefix `[SPEAKER_XX]: ` คั่นตาม Turn
- **`GET /export/srt`:** สร้าง Cue ในรูปแบบ:
  ```text
  1
  00:00:00,000 --> 00:00:01,500
  [SPEAKER_00]: สวัสดีครับ

  2
  00:00:01,800 --> 00:00:03,400
  [SPEAKER_01]: ยินดีที่ได้คุยกันครับ
  ```
- **`GET /export/json`:** คืน JSON Data ครบทั้ง metadata, duration, text และ segments (พร้อม speaker)

---

## 8. Web UI & Impacted Pages (หน้าเว็บและ UI ที่ได้รับผลกระทบ)

| Route | Template File | JS Handler | รายละเอียดการเปลี่ยนแปลงบนหน้าเว็บ |
|---|---|---|---|
| `/media/transcribe` | `app/templates/media.html` | `app/static/js/media.js` | 1. เพิ่ม Checkbox `🎙️ ระบุผู้พูด (Speaker Diarization)` ข้างตัวเลือกภาษา<br>2. ปรับ Stepper & Progress Bar ให้รองรับ Stage `diarizing`<br>3. ปรับ Result Box ให้แสดงผลแยก Turn ของผู้พูด |
| `/audio/transcribe` | `app/templates/upload.html` | `app/static/js/upload.js` | 1. เพิ่ม Checkbox `🎙️ ระบุผู้พูด (Speaker Diarization)` ข้าง Checkbox Timestamps<br>2. ส่ง `enable_diarization` ใน FormData ไปยัง `/v1/audio/transcribe`<br>3. แสดง Timestamps Box พร้อมระบุ Speaker Tag |
| `/audio/history` | `app/templates/transcribe_history.html` | `app/static/js/transcribe_history.js` | แสดง Badge `👥 Diarized` ในตารางประวัติงานสำหรับงานที่เปิดใช้งานระบุผู้พูด |
| API Docs Card (Audio) | `app/templates/partials/api_card_audio.html` | - | เพิ่มเอกสารพารามิเตอร์ `enable_diarization` (boolean) ในคำอธิบาย cURL / Python |
| API Docs Card (Media) | `app/templates/partials/api_card_media.html` | - | เพิ่มเอกสารพารามิเตอร์ `enable_diarization` (boolean) ในคำอธิบาย cURL / Python |

---

## 9. Testing Plan (unittest)

- **`tests/unit/transcription/test_diarization.py` (ใหม่):**
  - Unit test `merge_speaker_overlap()` ทดสอบคณิตศาสตร์ Overlap, Tie-break, และ Nearest-neighbor Fallback
  - Unit test `group_speaker_segments()` ทดสอบการรวมกลุ่มคำตาม Speaker
  - Unit test `build_srt_subtitles()` ทดสอบการแปลงเป็นไฟล์ SRT ที่มี speaker tags
- **`tests/unit/transcription/test_transcription_service.py`:**
  - เพิ่มการทดสอบ `FakeJobRepository` และ `create_job` ด้วย `enable_diarization=True`

---

## 10. File Change Checklist

| File Path | Action | Description |
|---|---|---|
| `requirements.txt` / `requirements-cpu.txt` | Modify | เพิ่ม `whisperx` (git) และ `pyannote.audio==3.1.1` |
| `.env.example` | Modify | เพิ่มคู่มือ `HF_TOKEN` และ `DIARIZATION_*` |
| `app/core/config.py` | Modify | เพิ่มค่าคอนฟิก `DIARIZATION_*` |
| `app/pyannote_engine.py` | **NEW** | Adapter สำหรับ PyAnnote 3.1 + Overlap Merge Algorithm |
| `app/whisperx_engine.py` | **NEW** | Adapter สำหรับ WhisperX Pipeline (ASR + Align + Diarize) |
| `app/db.py` | Modify | เพิ่มคอลัมน์ `enable_diarization` และ Migration |
| `app/modules/transcription/domain/entities.py` | Modify | เพิ่ม `enable_diarization` ใน Entity |
| `app/modules/transcription/adapters/outbound/repositories/sqlite_job_repository.py` | Modify | CRUD mapping คอลัมน์ `enable_diarization` |
| `app/modules/transcription/application/transcription_service.py` | Modify | ส่งต่อพารามิเตอร์ `enable_diarization` |
| `app/api/v1/transcription_router.py` | Modify | เพิ่ม Form param ใน endpoints + export SRT/TXT |
| `app/main.py` | Modify | ส่ง flag ใน Worker dispatcher |
| `app/modules/transcription/adapters/inbound/workers/run_job.py` + `app/run_job.py` | Modify | รับ flag ใน Worker subprocess |
| `app/job_worker.py` | Modify | เพิ่มขั้นตอน Diarization และจัดรูปแบบ Subtitles |
| `app/schemas.py` | Modify | เพิ่มฟิลด์ `speaker` และ Stage `diarizing` |
| `app/templates/media.html`, `upload.html` | Modify | เพิ่ม Checkbox UI |
| `app/static/js/media.js` | Modify | รองรับการส่ง Form และแสดงผลชื่อผู้พูด |
| `tests/unit/transcription/test_diarization.py` | **NEW** | Pure Unit tests สำหรับ Diarization Merge |
