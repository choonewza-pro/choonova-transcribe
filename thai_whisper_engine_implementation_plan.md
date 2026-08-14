# Implementation Plan: Switch Thai Offline Path to Thai-Tuned Whisper

> **ChooNova Transcribe: ยกระดับคุณภาพ Thai ASR + Diarization ให้เทียบเท่า Gemini reference**  
> สถานะ: **PLAN (draft)** — ยังไม่เริ่มพัฒนา รอพิจารณาแนวคิดจากผู้เชี่ยวชาญก่อน

---

## 1. ปัญหา (Problem)

ผลลัพธ์ปัจจุบันของ `test_3_talk.mp3` (TV talk show) ผ่าน Thai path (`typhoon-asr-realtime`):

- **CER 78%** เทียบกับ Gemini reference (`assets/test_3_talk.json`) — โดมด้วย hallucination insertions
- **Speaker attribution พัง**: SPEAKER_02 ได้ 480 คำ (จริงแค่ ~30) / SPEAKER_00 ได้ 90 (จริง ~hundreds)
- **ข้อความซ้ำซ้อน**: "สายนางนางนางไง..." "คุยกับมหาหมีดีกว่า..." ซ้ำ 3 ครั้ง
- **คำผิดเยอะ**: "ชมมนี"→"ชมดีเป็นตา", "ตาเฮียง"→"ตะเฮียง", "ประชดประชัน"→"ประชนประฉัน", "ดาวแปดแฉก"→"ดาวแปดแจก"

## 2. ต้นตอ (Root Causes — จากงานวิจัย)

1. **เลือก engine ผิดงาน** — `typhoon-asr-realtime` เป็น **streaming FastConformer-Transducer 114M** สร้างมาเพื่อ low-latency ไม่ใช่ offline accuracy  
   เปเปอร์ตัวเอง (arXiv:2601.13044) รายงาน TVSpeech CER:
   | Model | TVSpeech CER |
   |---|---|
   | Typhoon Whisper Large-v3 | 6.32% |
   | Typhoon Whisper Turbo | 6.85% |
   | Typhoon ASR Realtime (ใช้อยู่) | 9.99% |
   | Gemini 3 Pro | 10.95% |
   - ไฟล์ทดสอบเป็น TV talk show → Whisper-based Thai model ชนะทั้ง Typhoon และ Gemini
2. **RNN-T decode-loop hallucination** ("นางนางนาง") — ปัญหา implicit-LM overconfidence ที่รู้จักกันดี (ADAPTLMD ICASSP'22, LOOKAHEAD Interspeech'23, EDRL)  
   - Fix เป็น training-time หรือ NeMo-fork-level → **ไม่คุ้มค่า**
3. **Synthetic proportional timestamps ทำลาย diarization** — Typhoon ให้ text อย่างเดียว → ระบบ "เดา" ตำแหน่งคำแบบกระจายเท่าๆ กัน → `merge_speaker_overlap` ระบุผู้พูดผิด  
   - Whisper ให้ **word timestamps จริง** → speaker merge แม่นขึ้นทันที

## 3. แนวทางแก้ (Solution Direction)

**สลับ Thai offline path ไปใช้ Thai-tuned faster-whisper (CT2) แทน Typhoon**  
- Typhoon ยังเหลือไว้เฉพาะ **WebSocket/realtime path** (จุดที่มันออกแบบมา)
- En/auto path (Whisper `large-v3-turbo`) คงเดิม

### 3.1 โมเดลที่เลือก

| ตัวเลือก | โมเดล | Format | VRAM | หมายเหตุ |
|---|---|---|---|---|
| **A (แนะนำ)** | `Avocaduu14/whisper-th-large-v3-ct2` (Thonburian Whisper large-v3) | CT2 int8 → `int8_float16` บน GPU | ~2-3GB | CV13 Thai WER 6.59% |
| B (คุณภาพสูงกว่าแต่ VRAM มาก) | `mort666/whisper-large-v3-th-f16-faster` | CT2 fp16 | ~6GB | Thai finetune large-v3 |

> RTX 4080 Laptop 12GB — ตอนนี้ว่าง ~6GB (Typhoon 1GB + Whisper turbo 3.5GB resident)  
> ตัวเลือก A (int8) เป็นตัวเลือกปลอดภัยสุด

### 3.2 พารามิเตอร์ transcribe (ลด hallucination ตาม WhisperX)

```python
model.transcribe(
    audio_path,
    language="th",
    word_timestamps=True,
    vad_filter=True,
    condition_on_prev_text=False,   # WhisperX: ลด repetition/hallucination ใน long-form
    beam_size=5,
)
```

---

## 4. งานที่ต้องทำ (Tasks)

### 4.1 Engine ใหม่: `app/whisper_thai_engine.py`
- `WhisperEngine` subclass หรือ instance ใหม่ ผูกกับ `WHISPER_THAI_MODEL`
- ตาม pattern เดิมของ `WHISPER_MODEL` (config + lazy load + idle unload + lifecycle lock)
- `transcribe_file(...)` ใช้ `language="th"`, `word_timestamps=True`, `vad_filter=True`, `condition_on_prev_text=False`
- คืนค่าทั้ง **segment-level** และ **word-level timestamps** (จริง)

### 4.2 Routing: `app/engine_router.py`
- `transcribe_file()` / `transcribe_bytes()`:  
  - `lang == "th"` (offline) → `whisper_thai_engine`
  - `en` / `auto` → `whisper_engine` (เดิม)
  - `task == "translate"` → `whisper_engine` (เดิม)
- Typhoon ยังถูกใช้ที่ realtime/WebSocket path

### 4.3 Segment-level speaker assignment: `app/pyannote_engine.py`
- ฟังก์ชันใหม่ `assign_speakers_to_segments(segments, turns)`  
  - แต่ละ phrase segment → speaker ด้วย **max-overlap + nearest-turn fallback** (เดียวกับปรัชญา `merge_speaker_overlap` แต่ทำที่ระดับ segment)
  - Output shape ตรงกับ reference JSON: `{word, text, start, end, speaker}`

### 4.4 Router: `app/api/v1/transcription_router.py`
- Thai branch (บรรทัด ~208-236) เปลี่ยนเป็น:
  - `whisper_thai_engine.transcribe_file(..., with_timestamps=True)`
  - `assign_speakers_to_segments(...)` แทน `merge_speaker_overlap` + `group_speaker_segments`
  - `text` = `[SPEAKER]: phrase` lines
  - `timestamps` = phrase-level segments (ตาม reference)

### 4.5 Safety net
- คง `clean_text` / `collapse_repeated_tokens` ไว้ (กัน Whisper insertion)
- Long-form chunking ยังอยู่ใน engine

### 4.6 Config + docs
- `.env.example`: เพิ่ม `WHISPER_THAI_MODEL`
- `app/core/config.py`: `WHISPER_THAI_MODEL = os.getenv("WHISPER_THAI_MODEL", "Avocaduu14/whisper-th-large-v3-ct2")`
- AGENTS.md: อัปเดต Engine Routing section

### 4.7 Tests
- เพิ่ม unit tests ใน `tests/unit/transcription/test_diarization.py`:
  - `assign_speakers_to_segments` max-overlap / nearest-turn fallback / ไม่มี turn / UNKNOWN
  - Output format ตรง reference shape

### 4.8 Verify
- Rebuild container → รัน `test_3_talk.mp3` Thai + diarization
- วัด CER เทียบ `assets/test_3_talk.json` (ตั้งเป้า <20% จากเดิม 78%)
- เทียบ speaker attribution counts (SPEAKER_02 ≈ 3 turns)

---

## 5. ความเสี่ยง / Trade-off

- **VRAM เพิ่ม ~2-3GB** (int8) ขณะ Typhoon ยัง resident — ยังพอใน 12GB แต่ต้องเฝ้าระวัง
- **Latency สูงกว่า Typhoon** (offline เท่านั้น; realtime ยังใช้ Typhoon)
- Whisper ก็มี hallucination ได้บ้าง → ใช้ `condition_on_prev_text=False` + `collapse_repeated_tokens` เป็นเกราะ

---

## 6. ยังไม่เริ่ม (Blocked)

- รอแนวคิดจากผู้เชี่ยวชาญก่อนเริ่มพัฒนา
- หลังได้แนวคิด → อัปเดตแผนนี้ / หรือเปลี่ยนทิศทาง
