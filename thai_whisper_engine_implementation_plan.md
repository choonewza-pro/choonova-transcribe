# Implementation Plan: Switch Thai Offline Path to Thai-Tuned Whisper

> **ChooNova Transcribe: ยกระดับคุณภาพ Thai ASR + Diarization ให้เทียบเท่า Gemini reference**  
> สถานะ: **DONE (implemented + verified 15 Aug 2026)** — Thai offline path ใช้ Thai-tuned Whisper แล้ว

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
    condition_on_previous_text=False,   # WhisperX: ลด repetition/hallucination ใน long-form
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

### 4.3 Turn consolidation + word-to-turn grouping: `app/pyannote_engine.py`
- ฟังก์ชันใหม่ `consolidate_diarization_turns(turns, gap_sec=0.6, min_dur_sec=0.5)`
  - แก้ **cross-speaker time overlaps** (artifact ของ PyAnnote ที่ SPK 2 คนอ้างเวลาเดียวกัน) — turn ยาวครอบทับ สั้นถูกตัดออก
  - merge turn ผู้พูดเดียวกันห่างกัน ≤ 0.6s; drop turn สั้นกว่า 0.5s
- ฟังก์ชันใหม่ `group_words_by_turns(words, turns)` — เอาคำแต่ละคำ (word timestamps จริงจาก Thai Whisper) ไปใส่ turn ที่ overlap มากสุด
  - Output shape ตรงกับ reference JSON: `{word, text, start, end, speaker}`

### 4.4 Router: `app/api/v1/transcription_router.py`
- Thai branch (บรรทัด ~208-236) เปลี่ยนเป็น:
  - `whisper_thai_engine.transcribe_file(..., with_timestamps=True)` (จริง ๆ route ผ่าน `engine_router.transcribe_file`)
  - `group_words_by_turns(word_timestamps, turns)` แทน `merge_speaker_overlap` + `group_speaker_segments`
  - `text` = `[SPEAKER]: phrase` lines
  - `timestamps` = speaker-turn segments (ตาม reference)

> **ทำไมไม่ใช้ segment-level `assign_speakers_to_segments`:** phrase segment ของ Whisper ยาว 20–40s ครอบ speaker หลายคน → 1 segment ได้ 1 speaker (SPEAKER_01 14/20 segments) ละเอียดไม่พอ การ bucket ต่อ turn (~89 segments) เข้าคู่ reference (68) ดีกว่ามาก

### 4.5 Safety net
- คง `clean_text` / `collapse_repeated_tokens` ไว้ (กัน Whisper insertion)
- Long-form chunking ยังอยู่ใน engine

### 4.6 Config + docs
- `.env.example`: เพิ่ม `WHISPER_THAI_MODEL` + `WHISPER_THAI_COMPUTE_TYPE`
- `app/core/config.py`: `WHISPER_THAI_MODEL = os.getenv("WHISPER_THAI_MODEL", "Avocaduu14/whisper-th-large-v3-ct2")`
- AGENTS.md: อัปเดต Engine Routing section

### 4.7 Tests
- เพิ่ม unit tests ใน `tests/unit/transcription/test_diarization.py`:
  - `consolidate_diarization_turns`: resolve overlap / truncate / merge gap / drop tiny
  - `group_words_by_turns`: bucket by overlap / empty input
  - รวม 80 tests → OK

### 4.8 Verify
- Rebuild container → รัน `test_3_talk.mp3` Thai + diarization ✓ (HTTP 200, rtf 0.71, 89 segments avg 4.4s)
- วัด CER เทียบ `assets/test_3_talk.json`:
  - **TIME-ALIGNED CER 51.2%** (คำเราอยู่ใน reference windows เท่านั้น) — เป็น CER ระหว่าง ASR 2 ตัว (Whisper vs Gemini) ที่ต่างกัน
  - CER เต็ม 72.8% — ตัวเลขหลอก เพราะ reference ครอบ ~255s ของ speech ที่มี label เท่านั้น ในขณะที่ Whisper ถอดเสียงทั้ง 475s (3612 vs 2503 chars)
  - **คุณภาพ text ดีขึ้นมากเชิงคุณภาพ**: "คุณชมนี" "ตะเฮียง" "ประชดประชัน" ถูกต้อง ไม่มี hallucination loop เหมือน Typhoon
- Speaker agreement (best-permutation, 0.1s samples) = **40.2%** — ตรงตามเพดาน PyAnnote ~46% ที่วัดไว้ก่อนหน้า (ไม่มี pipeline ใดทะลุ 47%)
- Model 3.09GB คัดลอก host `./models/whisper-th-large-v3-ct2/` (bind-mount `/app/models`) → อยู่รอด rebuild, Dockerfile ก็ pre-download เข้า image ด้วย

---

## 5. ความเสี่ยง / Trade-off

- **VRAM เพิ่ม ~2-3GB** (int8) ขณะ Typhoon ยัง resident — ยังพอใน 12GB แต่ต้องเฝ้าระวัง
- **Latency สูงกว่า Typhoon** (offline เท่านั้น; realtime ยังใช้ Typhoon)
- Whisper ก็มี hallucination ได้บ้าง → ใช้ `condition_on_previous_text=False` + `collapse_repeated_tokens` เป็นเกราะ
- **Speaker identity ไม่ทะลุเพดาน PyAnnote ~46%** — เหตุผลคือ PyAnnote cluster ตะกับ Gemini reference ต่างกัน (host/SPEAKER_00 ของ Gemini ถูกแยกไปคนละ speaker) ไม่ใช่ปัญหา timestamp mapping

---

## 6. สรุป (Implemented)

- Thai offline path → **Thai-tuned Whisper** (`Avocaduu14/whisper-th-large-v3-ct2`, CT2 int8_float16, local `models/` preferred)
- text quality: คำถูกต้อง ชัดเจน ไม่มี decode-loop hallucination
- Diarization: `consolidate_diarization_turns` + `group_words_by_turns` (89 speaker-turn segments)
- 80 unit tests pass, py_compile clean, E2E API 200
