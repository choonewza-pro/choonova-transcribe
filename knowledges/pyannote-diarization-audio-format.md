# PyAnnote Diarization ช้าบน MP3 — สาเหตุและการแก้ไข

## สรุปปัญหา (Symptom)

ใช้หน้า `/audio/transcribe` (sync `POST /v1/audio/transcribe`) + Speaker Diarization กับไฟล์ **MP3 ยาว ~6.5 นาที**:

- ไม่มีผลลัพธ์นานมาก (เกือบ 11 นาที)
- GPU ทำงานตลอดแต่**ไม่สม่ำเสมอ** (util ต่ำ ~10-20%) — เพราะงานส่วนใหญ่เป็น CPU-bound decode ไม่ใช่ GPU compute
- ในที่สุดงานก็จบ (`PyAnnote diarization completed in 656.44s`) แล้วคืน `200 OK` — มันไม่ติดค้าง แต่ช้าสุด ๆ

## ต้นเหตุ (Root Cause)

PyAnnote `SpeakerDiarization` ต้องแยก **embeddings** ทุก chunk ของเสียง โดยเรียก `Audio.crop(file, chunk, ...)` ซ้ำทีละ chunk (ขว้าง 0.5s → ไฟล์ 393s มี ~786 chunk) และ `crop()` ของ pyannote จะ **เปิด/ถอดรหัสไฟล์ใหม่ทุกครั้งที่เรียก**

| ประเภทไฟล์ที่ป้อนให้ pyannote | เวลา crop 1 chunk (5s) | diarization ไฟล์ 393s ทั้งไฟล์ |
|---|---|---|
| MP3 (เดิม, 48kHz) | **~2.45s** | **656s (~11 นาที)** |
| WAV 16kHz mono | **~0.7ms** | **53s** |

ประมาณ **~3,500 เท่า** ช้าลงต่อ crop สำหรับ MP3 (ต้อง decode ทั้ง stream ถึงจุดที่ต้องการ) ส่วน WAV เป็น PCM ไม่บีบอัด เปิดอ่านแบบสุ่มได้ทันที

เส้นทาง `/media/transcribe` (async worker) **ไม่เจอปัญหานี้** เพราะ `job_worker.py` แปลงไฟล์เป็น `extracted_audio.wav` (16kHz mono) ด้วย `extract_audio_ffmpeg()` ก่อนป้อน pyannote อยู่แล้ว — เส้นทาง sync router เท่านั้นที่ส่งไฟล์เดิม (MP3/FLAC/OGG) ตรงเข้า pyannote

## วิธีแก้ (Fix)

`app/api/v1/transcription_router.py` ในบล็อก `enable_diarization` — หลังเขียนไฟล์ temp แล้ว แปลงเป็น WAV 16kHz mono ก่อนเสมอ แล้วส่ง WAV ไปยัง `diarize_audio()` / `transcribe_and_diarize_whisperx()`

```python
from app.audio_utils import extract_audio_ffmpeg
temp_wav_path = os.path.join(temp_dir, "diarization_input.wav")
await asyncio.to_thread(extract_audio_ffmpeg, temp_audio_path, temp_wav_path)
```

- `router_transcribe_file()` ยังอ่านไฟล์ต้นฉบับได้ตามเดิม (Typhoon/Whisper ถอดรหัส MP3 ภายในเองได้)
- ค่าใช้จ่ายการแปลง ~1-2s (ffmpeg speed ~900x) เทียบกับเวลาที่ประหยัดได้หลายร้อยวินาที
- ผลลัพธ์: 393s MP3 diarization ใช้เวลา ~55s แทน ~656s

## บทเรียน (Prevention)

1. **PyAnnote ต้องการ WAV 16kHz mono** (เป็นคำแนะนำทางการจาก pyannote เหมือนกัน) — ห้ามส่งไฟล์บีบอัด/ความถี่สูงตรงเข้า pyannote
2. ใช้ `extract_audio_ffmpeg()` (ใน `app/audio_utils.py`) เป็นจุดแปลงกลางเดียว ไม่เขียน ffmpeg ซ้ำเอง
3. ตรวจเส้นทางทั้งหมดที่เรียก `diarize_audio` / `transcribe_and_diarize_whisperx` ว่าป้อน WAV 16kHz mono ทุกจุด:
   - `job_worker.py` (media worker) ✅ แปลงแล้ว
   - `app/modules/transcription/adapters/outbound/media/ffmpeg_audio_adapter.py` (modular worker) ✅ แปลงแล้ว
   - `app/api/v1/transcription_router.py` (sync `/v1/audio/transcribe`) ✅ แก้แล้ว
4. อาการ "GPU ติดไม่สม่ำเสมอ + ไม่มีผลลัพธ์" ไม่ได้แปลว่า hang เสมอไป — ตรวจดู log ว่าไม่มีข้อความ `diarization completed in Xs` แล้ว X มากผิดปกติ
