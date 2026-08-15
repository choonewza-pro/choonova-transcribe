# GPU ทำงานเต็มทั้งสองตัว (Intel iGPU + NVIDIA) — สาเหตุที่แท้จริง

## สรุปปัญหา (Symptom)

รันหน้า `/audio/transcribe` (sync `POST /v1/audio/transcribe`) แบบ **Thai Whisper + ไม่แยกผู้พูด** บนเครื่องโน้ตบุ๊กแบบ hybrid GPU (Intel UHD Graphics + NVIDIA):

- **Intel UHD Graphics (iGPU):** ทำงานเต็ม ~92% **ตั้งแต่เริ่ม** ทันที
- **NVIDIA (dGPU):** ตอนแรกทำงานนิดเดียว **ค่อย ๆ ขึ้น** แล้วทำงานเต็ม 100%
- ผลสุดท้าย GPU ทั้งสองตัวแสดงว่า "เต็ม"

ผู้ใช้สันนิษฐานว่าเป็นเพราะ "Intel GPU ไม่มีตัวประมวลผล AI"

## ต้นเหตุ (Root Cause)

### AI ทำงานบน NVIDIA ตัวเดียวเท่านั้น

โมเดล Thai Whisper **ไม่เคยรันบน Intel iGPU เลย** เส้นทางจริงคือ:

```
/v1/audio/transcribe (FastAPI router)
  → subprocess python -m app.run_inline_transcribe
    → engine_router.transcribe_bytes()
      → whisper_thai_engine (faster-whisper / CTranslate2)
        → device="cuda"  ← NVIDIA เท่านั้น
```

- `app/core/config.py` กำหนด `DEVICE = "cuda"` เมื่อ `torch.cuda.is_available()` (บรรทัด 66-70)
- `WhisperEngine` (`app/whisper_engine.py`) ส่ง `device=self.device` ไปที่ `WhisperModel(...)` ของ faster-whisper
- ทั้งโปรเจกต์ไม่มี path ไหนเรียกใช้ iGPU (ไม่มี OpenCL/Vulkan/DirectML/oneAPI)

### NVIDIA ขึ้นช้า → เต็มทีหลัง (ปกติ ไม่ใช่ปัญหา)

1. **โหลดโมเดล:** `WhisperModel(...)` อ่านน้ำหนัก ~GB (CT2 int8_float16) จากดิสก์ → RAM → อัปโหลดขึ้น VRAM — ตอนนี้ NVIDIA ทำงานเบา (เฉพาะ copy engine) = "ทำงานนิดเดียว"
2. **Warm-up:** สร้าง CUDA context + cuDNN/cuBLAS autotune ครั้งแรก — GPU เริ่มไต่
3. **Steady-state:** transformer inference เป็นชุด — GPU เต็ม 100%

### Intel iGPU ขึ้น 92% ตั้งแต่เริ่ม (เป็น artifact ของการวัด ไม่ใช่ AI)

- **iGPU เป็น display adapter** — DWM (desktop compositing) รันบนตัวมัน ขณะ monitor (Task Manager / dashboard) รีเฟรชหน้าจอตลอดช่วง transcribe
- **iGPU ใช้ shared memory กับ CPU** (ไม่มี VRAM แยก) — ตอนโหลดโมเดล + inference มีการ copy ข้อมูล RAM↔GPU มหาศาล → memory controller ร่วมอิ่มตัว → Intel driver รายงาน "engine active" สูงเกินจริง
- Task Manager แสดง % ต่อ engine — engine **"Copy"** ที่ทำงานหนักจะอ่านเป็น % สูง ทั้งที่ไม่ได้ประมวลผล AI

**ดังนั้น "Intel GPU ไม่มีตัวประมวลผล AI" ไม่ใช่สาเหตุ** — มันไม่เคยถูกเรียกให้ทำงาน AI เลย ที่เห็น 92% คือค่าที่บิดเบือนจากการวัด

## วิธีพิสูจน์ (Verification)

1. รัน `nvidia-smi` — จะเห็นเฉพาะ NVIDIA โหลดจริง (VRAM + SM utilization) ส่วน iGPU ไม่โผล่เลย เพราะไม่ได้ใช้ CUDA
2. Task Manager → Performance → GPU 0 (Intel) → คลิกเลือก engine — ดูว่าที่ 92% คือ engine ตัวไหน:
   - ถ้าเป็น **"Copy"** = memory-transfer artifact (ข้อสรุปหลัก)
   - ถ้าเป็น **"3D"** = DWM compositing ของจอภาพ
   - จะเห็นว่า "Video Decode/Encode" ไม่เกี่ยวข้อง (ไฟล์เสียงไม่ได้ decode ด้วย hardware)

## ผลการวัดจริง (เครื่อง RTX 4080 Laptop GPU + Intel UHD Graphics, Docker Desktop)

เก็บข้อมูลด้วย PowerShell `\GPU Engine(*)\Utilization Percentage` + `nvidia-smi` ทุก 0.5s ระหว่างรัน
`POST /v1/audio/transcribe` (model=thai-whisper, ไฟล์ 12.96s, RTF 0.24):

| ช่วงเวลา | NVIDIA (LUID `0x0001cdd5`) | Intel iGPU (LUID `0x0001c9d3`) |
|---|---|---|
| ก่อนงาน (idle) | util ~1%, copy 21-30% (แอป Windows ธรรมดา) | ไม่โผล่ (ไม่มี engine ≥5%) |
| **ตอน infer (t≈15s)** | **`vmwp.exe engtype_3d = 99.9%`** — AI ทำงานจริง | **ไม่มี activity เลย** |
| หลังงาน (t≈68s) | util ~20-40% (Docker กำลังโหลดโมเดลใหม่) | `dwm.exe engtype_3d = 10.6%` (DWM เท่านั้น) |

**ข้อสรุปจากการวัด:** ตอนประมวลผล AI ตัวเดียวที่โหลด engine 3D 99.9% คือ `vmwp.exe` (WSL2 VM ของ
Docker) บน **NVIDIA** — Intel iGPU ไม่มี engine ไหนทำงานเลยตอน infer ส่วนที่เห็น iGPU "ขึ้น"
ใน Task Manager ขณะเปิดหน้าเว็บ คือ **DWM + เบราว์เซอร์ render หน้า dashboard** (poll ทุก 2s +
CSS animation) ซึ่ง composite บน display adapter ตามปกติ

### สิ่งที่แก้ไปแล้วเพื่อลด iGPU ที่โผล่ (frontend เท่านั้น, ไม่แตะ logic AI)

- `app/static/js/audio_jobs.js` + `media.js`: poll job status **2s → 5s** และ **ข้าม poll เมื่อ `document.hidden`**
- `app/static/js/model_status.js`: poll `/healthz` ขณะ model-loading dialog **1s → 2s** + ข้ามเมื่อ hidden
  และเพิ่ม global `visibilitychange` handler ที่ set class `page-hidden` บน `<html>`
- `app/static/css/style.css`: `html.page-hidden * { animation-play-state: paused }` — หยุด CSS animation
  ทั้งหมดเมื่อ tab ถูกซ่อน (ปิด GPU compositing ที่ไม่จำเป็น)
- `app/static/js/upload.js`: เลื่อนการโหลด audio preview (`URL.createObjectURL` + decode ลง `<audio>`)
  ไปหลังงานเสร็จ — ตอนเลือกไฟล์จะไม่ trigger GPU audio/video decode engine บน iGPU แล้ว
- Bump cache-busting version (`?v=`) ของไฟล์ static ที่แก้ทั้งหมด

> หมายเหตุ: การแก้ข้างต้นลดสัญญาณรบกวน (cosmetic) บน iGPU ระหว่างที่จ้องหน้าเว็บ แต่ **AI ยังทำงาน
> บน NVIDIA เสมอ** และ DWM (desktop compositing) ยังรันบน iGPU ตามธรรมชาติ — ถ้าต้องการให้ iGPU
> เหลือ 0% จริง ต้องตั้งค่าที่ Windows: NVIDIA Control Panel → บังคับเบราว์เซอร์ใช้ NVIDIA processor
> หรือเปิดโหมด dGPU only / MUX switch ใน MSI Center

## บทเรียน (Prevention)

1. **อย่าตีความ Task Manager GPU % บนเครื่อง hybrid ตรง ๆ** — iGPU ที่ขึ้นสูงไม่ได้แปลว่า model รันผิด GPU; ใช้ `nvidia-smi` เป็นแหล่งอ้างอิงการทำงานจริงของ AI
2. **เมื่อ debug "GPU ทำงานไม่เต็ม/เป็นช่วง"** ให้แยกช่วงเวลา: model load (GPU เบา) → warm-up (ขึ้น) → steady-state (เต็ม) — ถ้าไม่ถึง full load นาน ๆ แล้วมีผลลัพธ์ช้า ให้ดู CPU/disk/memory แทน
3. **ข้อควรรู้:** iGPU (Intel UHD) ไม่มี tensor/AI core แบบ NVIDIA — ถ้าบังคับให้รัน ASR บน iGPU จะช้าและอิ่มตัวเต็ม 100% ทันที นี่คือเหตุผลที่โปรเจกต์นี้บังคับ inference บน `cuda` (NVIDIA) เสมอเมื่อมี
4. ถ้าต้องการลดสัญญาณรบกวนบน iGPU (cosmetic เท่านั้น): ปิดรีเฟรชจอภาพ/monitor UI ระหว่างรัน หรือใช้จอแบบ dGPU exclusive