# Implementation Plan: Dependency Upgrade (Option C-lite — torch 2.8 / whisperx 3.8 / pyannote 4)

> **ChooNova Transcribe: ปลดล็อก torch จาก cu121 (2.5.1) ไป cu126 (2.8.0)** เพื่ออัปเกรด whisperx + pyannote + faster-whisper  
> สถานะ: **PLANNED (รออนุมัติ)** — ยังไม่แตะโค้ด/requirements จริง
> ขอบเขต: วิเคราะห์ความเสี่ยง + ขั้นตอนพิสูจน์แนวคิด (spike) ก่อนตัดสินใจ merge

---

## 1. เป้าหมาย (Goal)

อัปเกรด dependency ของ ML stack ที่ถูก lock อยู่กับ torch 2.5.1+cu121 ไปสู่เวอร์ชันที่ใหม่ขึ้น โดยเฉพาะ:

| ไลบรารี | ปัจจุบัน | เป้าหมาย | เหตุผล |
|---|---|---|---|
| `torch` / `torchaudio` | 2.5.1+cu121 | 2.8.0+cu126 | ปลดล็อก whisperx/pyannote |
| `torchvision` | (ไม่ได้ pin) | 0.23.0+cu126 | whisperx 3.8.6 บังคับ `~=0.23.0` |
| `whisperx` | 3.3.2 | 3.8.6 | Path 4 (en/auto + diarization) |
| `pyannote.audio` | 3.3.2 | 4.0.7 | Path 3 (thai + diarization) |
| `faster-whisper` | 1.1.0 | 1.2.1 | Thai-tuned Whisper engine |
| `transformers` | 4.46.3 | **4.48.3** | nemo 2.2.0 บังคับ `<=4.48.3` |
| `huggingface_hub` | 0.29.1 | ~0.34.x | transformers 4.48 ต้องการ `<1.0,>=0.34` |
| `numpy` | 1.26.4 | ~2.1 | whisperx 3.8.6 บังคับ `>=2.1.0` |
| `librosa` | 0.10.2.post1 | 1.0.0 | รองรับ numpy 2 (ต้อง `scipy>=1.15`) |
| `nemo-toolkit` | 2.1.0 | 2.1.0 (คงเดิม) หรือลอง 2.2.0 | **จุดเสี่ยงหลัก — ดู §5** |

## 2. สิ่งที่ "ไม่" ทำในแผนนี้ (Deliberately Out of Scope)

- ❌ **ไม่** อัปเกรด torch เกิน 2.8.x — whisperx 3.8.6 บังคับ `torch~=2.8.0` (`>=2.8.0,<2.9.0`)
- ❌ **ไม่** เอา `transformers 5.x` — nemo 2.x รับไม่ได้ (transformers 5 ต้องการ `huggingface-hub<2,>=1.5` + API break ใหญ่)
- ❌ **ไม่** เอา `nemo-toolkit 3.x` — เป็น major rewrite (module layout, API) เสี่ยงกับ Typhoon `.nemo` checkpoint
- ❌ **ไม่** เปลี่ยน base image Docker (ยังเป็น `python:3.12-slim`) — torch wheel cu126 แบก CUDA runtime เอง, driver host 610.88 รองรับ CUDA 12.6 แล้ว

## 3. ภาพรวม constraint chain (จากงานวิจัย PyPI)

### 3.1 ตัวดึงทุกอย่างขึ้น (The Puller)

`whisperx==3.8.6` ประกาศ dependency แบบเข้ม:

```
torch~=2.8.0          torchaudio~=2.8.0          torchvision~=0.23.0
pyannote-audio>=4.0.0
numpy>=2.1.0
faster-whisper>=1.2.0
transformers>=4.48.0
torchcodec<0.8.0,>=0.6.0
ctranslate2>=4.5.0
```

### 3.2 ตัวจำกัด (The Constrainer)

- `pyannote.audio==4.0.7`: `torch>=2.8.0`, `torchcodec>=0.7.0`, `transformers>=4.48.3` (extra separation), **`use_auth_token` → `token`** (breaking)
- `nemo-toolkit==2.2.0` (ถ้าเลื่อน): `transformers<=4.48.3,>=4.48.0`, `numba==0.61.0`, `sentencepiece<1.0.0`
- `transformers==4.48.3`: `huggingface-hub<1.0,>=0.34.0`
- `librosa==1.0.0`: `numpy>=2.1.0`, `scipy>=1.15.0`

### 3.3 เวอร์ชันที่ยืนยันว่ามีอยู่จริงใน index

| Package | cu126 index | cu128 index |
|---|---|---|
| torch | **2.8.0**–2.13.0 | 2.8.0–2.11.0 |
| torchaudio | 2.8.0–2.11.0 | 2.8.0–2.11.0 |
| torchvision | **0.23.0**–0.28.0 | **0.23.0**–0.26.0 |

> GPU host (RTX 4080 Laptop 12GB, driver **610.88**) รองรับ CUDA 12.6/12.8 ได้สบาย — ไม่ใช่ bottleneck

## 4. จุดเสี่ยงจากโค้ดจริง (ต้องแก้ code — ยังไม่ทำในแผนนี้)

### 4.1 `app/asr_engine.py` — Typhoon engine
- `:62` `import nemo.collections.asr` + `ASRModel.restore_from(typhoon-asr-realtime.nemo)`
- **ความเสี่ยง**: NeMo 2.1.0 ถูก build/test บน torch 2.5.0a0 (NVIDIA Software Component Versions) — ขึ้น torch 2.8 อาจเจอ CUDA graph / allocator corruption (เอกสารโปรเจกต์มี workaround `clear_cuda_cache`, `CUDA_RESET_BETWEEN_CHUNKS` อยู่แล้ว — บอกว่า fragility เป็นของจริง)

### 4.2 `app/pyannote_engine.py` — Thai diarization path
- `:731` `Pipeline.from_pretrained(use_auth_token=HF_TOKEN)` → pyannote 4 ลบ `use_auth_token` ต้องเปลี่ยนเป็น `token=`
- `:683` `from pyannote.audio.pipelines.speaker_diarization import SpeakerDiarization` → ต้องยืนยัน module path ใน 4.x
- Output schema ของ pipeline อาจเปลี่ยน (pyannote 4 ใช้ `DiarizeOutput` ใหม่ — มี community migration เตือนไว้)

### 4.3 `app/whisperx_engine.py` — Path 4
- `:77` `whisperx.load_model`, `:106` `DiarizationPipeline`, `:154` `load_align_model`, `:157` `align`, `:190` `assign_word_speakers`
- 3.3.2 → 3.8.6 API ส่วนใหญ่ stable แต่ต้องเทสต์จริง

### 4.4 `app/core/config.py` + `requirements*.txt`
- สลับ index `cu121` → `cu126` ทั้ง GPU และ CPU (`+cpu`), อัปเดต pin ทั้ง 2 ไฟล์ให้ตรงกัน

## 5. กลยุทธ์ลดความเสี่ยง (Risk Mitigation Strategy)

### 5.1 ลำดับการอัปเกรด (ทีละชั้น ไม่ใช่ทีเดียว)

| Phase | ขอบเขต | ความเสี่ยง |
|---|---|---|
| **P0 (แนะนำทำก่อน)** | Web tier + เฉพาะตัวที่ไม่มี chain: fastapi 0.141, uvicorn 0.52, pydantic 2.13, python-multipart, python-dotenv, jinja2, websockets 17, sentencepiece, soundfile, pythainlp 5.3, faster-whisper 1.2.1 | ✅ ต่ำมาก ไม่แตะ ML stack |
| **P1 (spike)** | torch 2.8.0+cu126 + whisperx 3.8.6 + pyannote 4.0.7 + transformers 4.48.3 + numpy 2.1 + librosa 1.0 — **แยก env / image ใหม่** | ⚠️ สูง — พิสูจน์ nemo 2.1.0 ยังรันบน torch 2.8 ได้ไหม |
| **P2 (ทางเลือก)** | ถ้า P1 พัง → ลอง `nemo-toolkit 2.2.0` (pin `transformers<=4.48.3` ตรงกับ whisperx พอดี) | ⚠️ สูง — numba==0.61.0 + numpy 2 conflict อาจมา |
| **P3 (ถอยหลัง)** | ถ้า nemo บน torch 2.8 ใช้ไม่ได้จริง → คง cu121 ไว้, ทำได้แค่ P0 + keep nemo ที่ 2.5.1 | — |

### 5.2 การทดสอบ (ไม่แตะโปรดักชัน)

1. สร้าง branch `feat/dep-upgrade-torch28`
2. สร้างไฟล์ `requirements-experiment.txt` (copy จาก GPU + เฉพาะ P1 ที่เปลี่ยน)
3. Build image แยก: `choonova-transcribe:torch28` (ไม่ชน `:latest`)
4. รัน smoke test บนไฟล์จริง:
   - **Path 3 (thai + diarization)**: `assets/test_3_talk.mp3` — Typhoon หรือ Thai Whisper + pyannote
   - **Path 4 (en + diarization)**: ไฟล์ eng + whisperx 3.8.6
   - เทียบ `text` / `segments` / speaker label กับผลปัจจุบัน (baseline)
5. ตรวจ `torch.cuda` no illegal memory access, no allocator corruption ใน loop หลายไฟล์ซ้ำๆ

## 6. Checklist งานจริง (เมื่ออนุมัติให้ implement)

- [ ] P0: อัปเดต web-tier pins ใน `requirements.txt` + `requirements-cpu.txt`
- [ ] P1: สร้าง requirements-experiment + image แยก, รัน smoke test, เก็บบันทึกผล
- [ ] ตัดสินใจ nemo: คง 2.1.0 / เลื่อน 2.2.0 / ถอย cu121 (ตามผล P1)
- [ ] แก้ `app/pyannote_engine.py`: `use_auth_token`→`token`, ยืนยัน module path + output schema 4.x
- [ ] แก้ `app/whisperx_engine.py` ถ้า API 3.8.6 ต่างจาก 3.3.2
- [ ] สลับ index `cu121`→`cu126` + ขึ้น pin ให้ตรงกันทั้ง GPU/CPU
- [ ] รัน test suite: `python -m unittest discover -s tests/unit -t . -v`
- [ ] Rebuild + deploy test บน GPU จริง ตรวจ `/healthz` + 1 รอบ end-to-end ต่อ path
- [ ] อัปเดต AGENTS.md (Engine Routing section: CUDA index, torch version)

## 7. สิ่งที่ยังเป็น open question (ต้องตัดสินใจก่อน implement)

1. **nemo 2.1.0 บน torch 2.8** — ไม่มีใครรับประกันได้บน paper ต้อง spike จริง
2. **transformers 4.48.3 เท่านั้น** (ล็อกไว้ไม่ให้ขึ้น 5.x) — user ยอมรับ trade-off ไหม
3. **numpy 2.x** จะกระทบ numba/pyannote/speechbrain local model path (`models/pyannote/`, `models/speechbrain/`) — ต้องเทสต์
4. `websockets 14→17` เป็น major version — realtime router ต้องเทสต์ WebSocket flow (มี doc: `knowledges/realtime-streaming-architecture.md`)
5. CPU path (`requirements-cpu.txt`) ต้องอัปเดตคู่กัน — `torch==2.8.0+cpu` มีใน index

## 8. สรุปความเสี่ยง (Executive Summary)

- **เป้าหมายสมเหตุสมผล**: ปลดล็อก torch 2.8 → อัป whisperx/pyannote/faster-whisper ได้จริง มี wheel ครบใน cu126
- **gate ตัวเดียวที่ตัดสินได้ด้วย experiment**: nemo-toolkit (Typhoon) บน torch 2.8 — ถ้า pass แผนนี้ไปได้ไกล
- **fallback ชัดเจน**: ถ้า nemo พัง → เหลือ P0 (web tier + faster-whisper) ปลอดภัย 100%
- **ไม่ทำ**: transformers 5.x, nemo 3.x, torch 2.9+ — เกินขอบเขตปลอดภัยของ codebase นี้