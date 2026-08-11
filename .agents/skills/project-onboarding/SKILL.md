---
name: project-onboarding
description: Use this skill when a developer asks how to set up, run, or understand this Python/FastAPI Typhoon ASR & Whisper transcription project. Use for onboarding questions such as "โปรเจกต์นี้ตั้งค่าอย่างไร", "เริ่มรันยังไง", "ใช้ stack อะไร", or Docker/GPU/CPU setup questions from someone new to the codebase.
license: MIT
metadata:
  author: choonewza@gmail.com
  version: "1.1.0"
---

# Project Onboarding Skill

ช่วย developer ใหม่เข้าใจโปรเจกต์ **Choonova Transcribe** จาก clone ไปจนรัน local / Docker ได้ โดยต้องอ้างอิงจากไฟล์จริงใน repo ก่อนตอบเสมอ

---

## 📌 Project Overview

**Choonova Transcribe** คือบริการ Thai speech-to-text API service ที่ขับเคลื่อนด้วย:
- **Primary ASR Engine:** **Typhoon ASR Realtime** (FastConformer-Transducer 114M) สำหรับเสียงภาษาไทย
- **Secondary Engine:** **Whisper** (faster-whisper) สำหรับภาษาอังกฤษ หรือ mixed Thai-English
- **Backend Framework:** **Python 3.12 + FastAPI + PyTorch / NeMo**
- **Hardware Target:** NVIDIA GPU (เช่น RTX 4080 12GB VRAM) หรือ CPU/Mac Apple Silicon

---

## 🏗️ Architecture & Core Components

- **Main Entrypoint:** [app/main.py](file:///d:/_PROJECT_/choonova-transcribe/app/main.py) — FastAPI application, route registration, WebSockets, periodic cleanup task
- **Config & Settings:** [app/config.py](file:///d:/_PROJECT_/choonova-transcribe/app/config.py) — อ่านสภาพแวดล้อม (.env), ตั้งค่า VRAM load mode (`always` / `idle`), chunk retention, operational limits
- **Authentication:** [app/auth.py](file:///d:/_PROJECT_/choonova-transcribe/app/auth.py) — API key verification middleware (Bearer / x-api-key / query param)
- **Database Repository:** [app/db.py](file:///d:/_PROJECT_/choonova-transcribe/app/db.py) — SQLite database (`data/choonova-transcribe.db`) จัดการประวัติ job และ settings
- **ASR Engine:** [app/asr_engine.py](file:///d:/_PROJECT_/choonova-transcribe/app/asr_engine.py) — NeMo Singleton Wrapper & Whisper engine integration
- **Audio Processing:** [app/audio_utils.py](file:///d:/_PROJECT_/choonova-transcribe/app/audio_utils.py) — สกัด/ตัดแบ่งไฟล์เสียงด้วย FFmpeg & ตรวจสอบพื้นที่ดิสก์
- **Job Processing Worker:** [app/job_worker.py](file:///d:/_PROJECT_/choonova-transcribe/app/job_worker.py) — Async pipeline สำหรับงาน long-form transcription

---

## ⚡ Quick Setup Guide

1. **คัดลอกไฟล์ Environment Variables:**
   ```bash
   cp .env.example .env
   ```

2. **เลือกรูปแบบการรัน (Local vs Docker):**

### 💻 Local Execution
```bash
# GPU environment (CUDA 12.1 PyTorch required)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8830

# CPU environment (Mac M1-M5 / Windows CPU)
pip install -r requirements-cpu.txt
DEVICE=cpu uvicorn app.main:app --host 0.0.0.0 --port 8830
```

### 🐳 Docker Execution
```bash
# Docker Network (สร้างครั้งแรกถ้ายังไม่มี)
docker network create km4u-network

# GPU Mode (Nvidia Container Toolkit required)
docker compose up -d --build

# CPU Mode (Mac M-Series / PC without GPU)
docker compose -f docker-compose-cpu.yml up -d --build
```

---

## ⚠️ Key Gotchas & Considerations

- **Docker Configs:** ตรวจสอบทั้ง `Dockerfile` (GPU) และ `Dockerfile.cpu` (CPU) หากอัปเดต dependencies
- **Docker Compose Files:**
  - `docker-compose.yml`: GPU Mode (รองรับ NVIDIA RTX)
  - `docker-compose-cpu.yml`: CPU Mode (สำหรับ Mac M-Series / Windows CPU)
  - `docker-compose-km4u.yml`: Production / Deployment integration
- **Model Files:** ไฟล์โมเดล `.nemo` จะถูกดาวน์โหลดอัตโนมัติจาก HuggingFace (`typhoon-ai/typhoon-asr-realtime`) ไว้ที่ `model/` (gitignored)
- **VRAM Management:** สามารถปรับ VRAM residency ใน Dashboard (`http://localhost:8830/`) หรือ env (`MODEL_LOAD_MODE=always|idle`)
- **Dashboard & API Specs:** เข้าดู Web Dashboard และ Interactive API docs ได้ที่ `http://localhost:8830/docs` หรือ `http://localhost:8830/`

---

## 📋 Response Format Guidelines

เมื่อตอบคำถาม setup หรือ onboarding ให้สรุปข้อมูลสั้นกระชับ ครอบคลุมหัวข้อต่อไปนี้เสมอ:
1. ภาพรวมสั้น ๆ ของ Stack & Architecture (Python 3.12 / FastAPI / Typhoon ASR / Whisper)
2. ตารางขั้นตอน Setup & คำสั่งรันที่ถูกต้อง (GPU vs CPU)
3. ข้อควรระวังเฉพาะของ repo นี้ (Docker network, GPU drivers, VRAM mode)

