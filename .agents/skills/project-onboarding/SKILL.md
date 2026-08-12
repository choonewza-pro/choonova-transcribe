---
name: project-onboarding
description: Use this skill when a developer asks how to set up, run, or understand this Python/FastAPI Typhoon ASR & Whisper transcription project. Use for onboarding questions such as "โปรเจกต์นี้ตั้งค่าอย่างไร", "เริ่มรันยังไง", "ใช้ stack อะไร", or Docker/GPU/CPU setup questions from someone new to the codebase.
license: MIT
metadata:
  author: choonewza@gmail.com
  version: "1.2.0"
---

# Project Onboarding Skill

ช่วยให้ developer หรือ AI Agent สามารถติดตั้ง กำหนดค่า รัน และตรวจสอบความพร้อมของระบบ **Choonova Transcribe** ได้อย่างสมบูรณ์แบบ ทั้งการรันบน Docker และแบบ Local Host ด้วย `.venv`

---

## 📌 Project Overview

**Choonova Transcribe** คือบริการ Thai speech-to-text API service ที่พัฒนาขึ้นโดยใช้:
- **Primary ASR Engine:** **Typhoon ASR Realtime** (FastConformer-Transducer 114M) สำหรับภาษาไทย
- **Secondary Engine:** **Whisper** (faster-whisper `large-v3-turbo`) สำหรับภาษาอังกฤษ หรือ Mixed Thai-English
- **Backend Framework:** **Python 3.12 + FastAPI + PyTorch / NeMo**
- **Hardware Target:** NVIDIA GPU (เช่น RTX 4080 12GB VRAM ขึ้นไป สำหรับ GPU Mode) หรือ CPU / Mac Apple Silicon

---

## 🏗️ Core Codebase Structure

- **Main Entrypoint:** [app/main.py](file:///d:/_PROJECT_/choonova-transcribe/app/main.py) — ไฟล์หลักสำหรับเปิดระบบ FastAPI, ลงทะเบียนเราเตอร์, และตั้งค่างานเบื้องหลัง
- **Configuration:** [app/core/config.py](file:///d:/_PROJECT_/choonova-transcribe/app/core/config.py) — ดึงค่าจากสภาพแวดล้อม (.env) เพื่อตั้งค่า VRAM, ขนาดอัปโหลด, และการจัดการหน่วยความจำ
- **Database:** [app/core/db.py](file:///d:/_PROJECT_/choonova-transcribe/app/core/db.py) — เชื่อมต่อ SQLite Database (`data/choonova-transcribe.db`) ในโหมด WAL สำหรับเก็บประวัติงาน
- **ASR Engine Service:** [typhoon_adapter.py](file:///d:/_PROJECT_/choonova-transcribe/app/modules/transcription/adapters/outbound/engines/typhoon_adapter.py) และ [whisper_adapter.py](file:///d:/_PROJECT_/choonova-transcribe/app/modules/transcription/adapters/outbound/engines/whisper_adapter.py) — การรวมระบบตัวแปลงเสียง NeMo และ Whisper
- **FFmpeg Adapter:** [ffmpeg_audio_adapter.py](file:///d:/_PROJECT_/choonova-transcribe/app/modules/transcription/adapters/outbound/media/ffmpeg_audio_adapter.py) — ใช้สำหรับจัดการไฟล์เสียงและประมวลผลเสียงด้วย FFmpeg
- **Video Compressor Adapter:** [ffmpeg_adapter.py](file:///d:/_PROJECT_/choonova-transcribe/app/modules/compression/adapters/outbound/ffmpeg_adapter.py) — ใช้สำหรับบีบอัดไฟล์วิดีโอด้วย FFmpeg

---

## 🔍 Pre-check Checklist (สำหรับตรวจสอบเครื่องตนเองก่อนติดตั้ง)

ก่อนจะทำการติดตั้ง ให้ตรวจสอบความพร้อมของสภาพแวดล้อมดังนี้:

1. **ตรวจสอบความพร้อมของ Python 3.12**
   ```bash
   python --version
   ```
2. **ตรวจสอบความพร้อมของ FFmpeg** (เนื่องจากโปรเจกต์นี้อาศัย FFmpeg ในการประมวลผลเสียงและบีบอัดวิดีโอ)
   - *Windows (PowerShell):* `Get-Command ffmpeg` หรือ `ffmpeg -version`
   - *Mac (Terminal):* `brew list ffmpeg` หรือ `ffmpeg -version`
   - *Ubuntu/Linux:* `which ffmpeg` หรือ `ffmpeg -version`
   - **วิธีติดตั้ง FFmpeg หากยังไม่มี:**
     - **Windows:** `winget install FFmpeg` หรือ `choco install ffmpeg`
     - **Mac:** `brew install ffmpeg`
     - **Ubuntu/Debian:** `sudo apt update && sudo apt install -y ffmpeg`
3. **ตรวจสอบว่าต้องการรันผ่าน GPU หรือไม่ (NVIDIA GPU)**
   - ตรวจสอบ NVIDIA Driver และ CUDA Compatibility: `nvidia-smi`
   - สำหรับ Docker GPU: ต้องแน่ใจว่าติดตั้ง [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) เรียบร้อยแล้ว

---

## ⚡ 1. การติดตั้งแบบ Local Host (ผ่าน Virtual Environment - `.venv`)

การติดตั้งโดยรันตรงบนตัวเครื่องเหมาะอย่างยิ่งกับการพัฒนาและการรันทดสอบด่วน:

### ขั้นตอนการรันคำสั่ง (Step-by-Step):

1. **สร้างสภาพแวดล้อมเสมือน (Virtual Environment):**
   ```bash
   python -m venv .venv
   ```

2. **เปิดการใช้งาน (Activate) สภาพแวดล้อมเสมือน ตามระบบปฏิบัติการและเชลล์ของคุณ:**
   - **Windows (PowerShell):**
     ```powershell
     Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
     .venv\Scripts\Activate.ps1
     ```
   - **Windows (CMD):**
     ```cmd
     .venv\Scripts\activate.bat
     ```
   - **Linux / macOS:**
     ```bash
     source .venv/bin/activate
     ```

3. **อัปเกรด pip ก่อนทำการติดตั้งเสมอ (เพื่อหลีกเลี่ยงข้อผิดพลาดในการดึง dependencies ขนาดใหญ่):**
   ```bash
   python -m pip install --upgrade pip
   ```

4. **ติดตั้ง Dependencies ตามโหมดที่ต้องการ:**
   - **สำหรับเครื่องที่มี NVIDIA GPU (CUDA 12.1):**
     ```bash
     pip install -r requirements.txt
     ```
   - **สำหรับเครื่องที่เป็น CPU-Only หรือ Apple Silicon (Mac M1-M5):**
     ```bash
     pip install -r requirements-cpu.txt
     ```

5. **สร้างไฟล์ปรับแต่งระบบ (.env):**
   - คัดลอกเทมเพลต:
     - *Windows (PowerShell):* `Copy-Item .env.example .env`
     - *Unix / Windows CMD:* `cp .env.example .env`
   - เข้าไปแก้ไขไฟล์ `.env` โดยเฉพาะตัวแปรสำคัญ:
     - `DEVICE`: ตั้งค่าเป็น `cuda` หรือ `cpu` ตามอุปกรณ์ที่คุณมี
     - `GATEWAY_API_KEY`: เปลี่ยนรหัสผ่านสำหรับ Authenticate API (ค่าเริ่มต้นคือ `change-me-in-production`)

6. **ตรวจสอบว่ามีพอร์ตว่างหรือไม่ (พอร์ตหลักคือ 8830):**
   - *Windows (PowerShell):* `Get-NetTCPConnection -LocalPort 8830 -ErrorAction SilentlyContinue`
   - *Linux/macOS:* `ss -lntp | grep 8830` หรือ `netstat -an | grep 8830`

7. **เริ่มรันระบบ:**
   - **โหมด GPU:**
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port 8830
     ```
   - **โหมด CPU:**
     - *Windows PowerShell:*
       ```powershell
       $env:DEVICE="cpu"
       uvicorn app.main:app --host 0.0.0.0 --port 8830
       ```
     - *Windows CMD:*
       ```cmd
       set DEVICE=cpu
       uvicorn app.main:app --host 0.0.0.0 --port 8830
       ```
     - *Linux / macOS / Git Bash:*
       ```bash
       DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
       ```

---

## 🐳 2. การติดตั้งแบบ Container (ผ่าน Docker)

ระบบมี Docker และ Docker Compose สนับสนุนทั้งการรันผ่าน CPU และ GPU

### ขั้นตอนการรันคำสั่ง (Step-by-Step):

1. **ตรวจสอบสถานะ Docker Daemon:**
   ```bash
   docker info
   ```

2. **เตรียมไฟล์สภาพแวดล้อม (.env):**
   - ทำการคัดลอกไฟล์เทมเพลต:
     ```bash
     cp .env.example .env
     ```
   - ตั้งค่าตัวแปร `DEVICE` ให้สอดคล้องกับที่จะรัน (`cpu` หรือ `cuda`)

3. **สร้าง Docker Network ภายนอก (External Network):**
   - ใน `docker-compose.yml` และ `docker-compose-km4u.yml` มีการผูกกับเน็ตเวิร์กภายนอกที่ชื่อ `km4u-network` ให้สร้างรอก่อนด้วยคำสั่ง:
     ```bash
     docker network create km4u-network
     ```
   - *หมายเหตุ:* สำหรับ `docker-compose-cpu.yml` ไม่จำเป็นต้องสร้างเน็ตเวิร์กนี้เนื่องจากตั้งค่าเน็ตเวิร์กแยกต่างหาก

4. **สั่ง Build และดึงระบบขึ้นทำงาน (Up Containers):**
   - **โหมด GPU (เครื่องที่มีการ์ดจอ NVIDIA และเปิดใช้งาน NVIDIA Container Toolkit):**
     - หากต้องการรันระบบแบบเดี่ยว (Standalone):
       ```bash
       docker compose up -d --build
       ```
     - หากต้องการรันระบบเพื่อเชื่อมต่อกับโปรเจกต์เครือข่าย KM4U:
       ```bash
       docker compose -f docker-compose-km4u.yml up -d --build
       ```
   - **โหมด CPU (สำหรับเครื่องทั่วไปที่ไม่มีการ์ดจอ หรือ Mac Apple Silicon):**
     ```bash
     docker compose -f docker-compose-cpu.yml up -d --build
     ```

5. **ตรวจสอบความถูกต้องของการรัน:**
   - เช็คสถานะ Container: `docker compose ps` (หรือระบุไฟล์ `-f docker-compose-cpu.yml ps` ตามโหมดที่รัน)
   - ตรวจดู Logs ของบริการ: `docker compose logs -f transcribe`

---

## ✅ 3. การตรวจสอบความถูกต้องและการทำสอบระบบ (System Verification)

เมื่อระบบรันเรียบร้อยแล้ว ให้ทำการทดสอบเพื่อยืนยันว่าระบบทำงานถูกต้อง:

### 1. ทดสอบการตอบรับ API (Health Check)
เปิดเว็บบราวเซอร์หรือยิงคำสั่ง curl ไปที่:
```bash
curl http://localhost:8830/healthz
```
*ตัวอย่างคำตอบที่ถูกต้อง:* `{"status":"ok", "engines": ...}`

### 2. ทดสอบยิงทดสอบระบบยูนิตเทส (Unit Tests)
หากอยู่ในโหมด Local host และติดตั้ง dependencies เรียบร้อย ให้รันการทดสอบยูนิตเทส:
```bash
# รันเทสทั้งหมดในส่วน Unit Test
python -m unittest discover -s tests/unit -t . -v

# รันเทสเฉพาะโมดูลการตั้งค่า
python -m unittest tests.unit.settings.test_settings_service
```

### 3. ตรวจสอบความถูกต้องของการโหลด PyTorch & CUDA (สำหรับ GPU)
เช็คให้แน่ใจว่า PyTorch มองเห็นการ์ดจอ NVIDIA ในสภาวะปัจจุบัน:
```bash
python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('Device Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
```

### 4. ตรวจสอบความถูกต้องของ NVIDIA GPU & NVENC ใน Container (GPU/NVENC Troubleshooting)
หากมีพฤติกรรมหน่วง หรือการบีบอัดวิดีโอตกไปใช้ `libx264` (Fallback) ทั้งที่เปิดโหมด GPU ให้ใช้คำสั่งเหล่านี้ทดสอบการแชร์ทรัพยากร GPU เข้าไปใน Docker:

1. **ตรวจสอบความพร้อมของ GPU บนเครื่องโฮสต์ (Host GPU):**
   ```bash
   nvidia-smi
   ```

2. **ตรวจสอบการฉีดอุปกรณ์ GPU เข้า Docker Container:**
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
   ```

3. **ตรวจสอบความพร้อมของไดรเวอร์และไลบรารี NVENC ภายใน Container:**
   ```bash
   # เช็คการ mount ไฟล์ไดรเวอร์วิดีโอ (libnvidia-encode) เข้า container
   docker exec choonova-transcribe ls /usr/lib/x86_64-linux-gnu/ | grep -E 'libnvidia-encode|libnvcuvid'

   # ตรวจสอบการตอบรับฮาร์ดแวร์เอ็นโค้ดเดอร์ h264_nvenc ผ่าน FFmpeg
   docker exec choonova-transcribe ffmpeg -h encoder=h264_nvenc >/dev/null && echo "h264_nvenc OK"
   ```

---

## 🛠️ คำแนะนำพิเศษสำหรับ AI Agent (AI Agent Execution Guidelines)

หากคุณเป็น AI Agent ที่ต้องทำการ Setup โครงการนี้ด้วยตนเอง ให้ปฏิบัติตามกฎเหล็กนี้:

1. **อย่ารันคำสั่งโดยไม่เช็คสถานะระบบก่อน:** ตรวจสอบพอร์ต 8830 เสมอว่าว่างอยู่หรือไม่ด้วยคำสั่งตรวจสอบพอร์ตที่ระบุไว้ข้างต้น เพื่อเลี่ยงข้อผิดพลาด port conflicts
2. **หากต้องการให้โปรแกรมรันค้างเป็นเบื้องหลัง (Background Service):**
   - อย่ารัน uvicorn ด้วยคำสั่งแบบ Blocking ยาว ๆ บนเทอร์มินัลหลักตรง ๆ
   - ให้แนะนำหรือรันผ่าน Docker compose (`-d`) เป็นทางเลือกแรก หรือรัน command เป็น Background task/daemon
3. **การดาวน์โหลดโมเดล:** เมื่อรันครั้งแรก ระบบจะดาวน์โหลดโมเดล Typhoon (ประมาณ 1.1GB) และ Whisper (ประมาณ 1.5GB-2GB) จาก Hugging Face หากอินเทอร์เน็ตช้าหรือติดปัญหา Timeout ให้แจ้งผู้ใช้งานเพื่อขอ HF_TOKEN หรือขยายการรอโหลดในสคริปต์
4. **การรันคำสั่งใน Windows:**
   - ระวังข้อผิดพลาดของ Mojibake หากมีคำภาษาไทยในเอาต์พุตของเทอร์มินัล Windows ให้ตั้งค่า encoding ของคอนโซลเป็น UTF-8 (เช่น `chcp 65001`) หรือใช้ Python ในการประมวลผลเอาต์พุตเพื่อป้องกันปัญหา Mojibake


