---
name: modular-hexagonal-architecture
description: >
  Use this skill whenever developing, refactoring, or extending features in ChooNova Transcribe.
  Enforces the Pragmatic Modular Monolith + Hexagonal Architecture principles, layer boundaries,
  dependency rules, and coding standards. Trigger on: "architecture", "add module", "refactor",
  "add port", "add adapter", "create usecase", "new feature", or working within app/modules/ or app/core/.
metadata:
  author: choonewza@gmail.com
  version: "1.0.0"
---

# Pragmatic Modular Monolith + Hexagonal Architecture Guidelines

สกิลนี้เป็นมาตรฐานสถาปัตยกรรมระบบของ **ChooNova Transcribe** ให้ AI Coding Agent และนักพัฒนาทุกคนยึดถือเป็นกฎเหล็กในการสร้าง, แก้ไข, หรือ refactor โค้ดในโปรเจกต์นี้

---

## 📐 1. ภาพรวมสถาปัตยกรรม (Architecture Overview)

โปรเจกต์ใช้โครงสร้าง **Pragmatic Modular Monolith + Hexagonal Architecture (Ports and Adapters)** โดยแบ่งระบบออกเป็น Bounded Context Modules ที่ชัดเจน:

```text
                               ┌──────────────────────────┐
                               │       Delivery Layer     │
                               │   FastAPI / WebSockets   │
                               └────────────┬─────────────┘
                                            │
                                            ▼
                               ┌──────────────────────────┐
                               │    Application Layer     │
                               │   Use Cases / Services   │
                               └────────────┬─────────────┘
                                            │
                                            ▼
                               ┌──────────────────────────┐
                               │       Domain Layer       │
                               │   Entities / Rules /     │
                               │       Ports (Interfaces) │
                               └────────────┬─────────────┘
                                            │
                ┌───────────────────────────┼───────────────────────────┐
                ▼                           ▼                           ▼
     ┌────────────────────┐     ┌──────────────────────┐    ┌─────────────────────┐
     │  SQLite Adapters   │     │  ASR Model Adapters  │    │   FFmpeg Adapters   │
     │(Settings, Jobs...) │     │  (Typhoon, Whisper)  │    │(Audio, Compression) │
     └────────────────────┘     └──────────────────────┘    └─────────────────────┘
```

---

## 🚫 2. กฎเหล็กด้าน Dependency (Strict Dependency Rules)

1. **Domain Layer (`app/modules/<module>/domain/`)**:
   - **ห้ามรู้จัก** Framework หรือ External Infrastructure ใดๆ ทั้งสิ้น (`FastAPI`, `SQLite`, `PyTorch`, `NeMo`, `Whisper`, `FFmpeg`, `Docker`)
   - ประกอบด้วย pure Python `dataclasses`, Domain Rules, Domain Exceptions, และ **Ports (Interfaces)** เท่านั้น

2. **Application Layer (`app/modules/<module>/application/`)**:
   - รู้จักเฉพาะ **Domain** และ **Ports** เท่านั้น
   - **ห้าม import** Concrete Outbound Adapters (เช่น `SQLiteJobRepository` หรือ `TyphoonAdapter`) โดยตรงใน Use Case Class — ต้องสั่งงานผ่าน **Port Interfaces** เสมอ

3. **Adapters Layer (`app/modules/<module>/adapters/`)**:
   - **Inbound Adapters**: สิ่งที่เรียกเข้ามาหา Application (FastAPI Routers, WebSocket Controllers, Worker Subprocess CLI)
   - **Outbound Adapters**: สิ่งที่ Application เรียกออกไปภายนอก (SQLite Repositories, Typhoon ASR, Whisper, FFmpeg, Filesystem)

4. **Core Infrastructure (`app/core/`)**:
   - รวม Cross-cutting concerns (`config.py`, `security.py`, `db.py`, `exceptions.py`, `logging.py`)
   - `app/core/db.py` ทำหน้าที่เป็น SQLite Connection Factory ที่บังคับใช้ **WAL Mode (`PRAGMA journal_mode=WAL;`)** และ `busy_timeout=30000` สำหรับทุก Repository

---

## 📂 3. โครงสร้าง Directory มาตรฐาน (Standard Directory Structure)

```text
app/
├── core/                                # Shared Infrastructure & Cross-cutting Concerns
│   ├── config.py                        # Centralized Environment Variables
│   ├── security.py                      # API Key Verification (x-api-key)
│   ├── db.py                            # SQLite WAL Connection Pool Engine
│   ├── exceptions.py                    # Base Exceptions Hierarchy
│   └── logging.py                       # Structured Logger Setup
│
├── modules/                             # Bounded Context Modules
│   │
│   ├── settings/                        # Model VRAM Settings Module
│   │   ├── domain/ (entities.py, ports.py)
│   │   ├── application/ (settings_service.py)
│   │   └── adapters/
│   │       └── outbound/ (sqlite_settings_repository.py)
│   │
│   ├── compression/                     # Video/Audio Compression Module
│   │   ├── domain/ (entities.py, ports.py)
│   │   ├── application/ (compression_service.py)
│   │   └── adapters/
│   │       ├── inbound/workers/ (run_compress_job.py)
│   │       └── outbound/ (ffmpeg_adapter.py, repositories/sqlite_compress_repository.py)
│   │
│   └── transcription/                   # ASR Transcription Module
│       ├── domain/ (entities.py, ports.py)
│       ├── application/ (transcription_service.py)
│       └── adapters/
│           ├── inbound/workers/ (run_job.py)
│           └── outbound/
│               ├── engines/ (typhoon_adapter.py, whisper_adapter.py, engine_router.py)
│               ├── media/ (ffmpeg_audio_adapter.py)
│               └── repositories/ (sqlite_job_repository.py)
│
├── api/                                 # Delivery Layer
│   ├── v1/                              # REST & WebSocket API Routers
│   │   ├── settings_router.py
│   │   ├── compression_router.py
│   │   ├── transcription_router.py
│   │   └── realtime_router.py
│   └── web/                             # HTML Dashboard View Routers
│       └── views_router.py
│
└── main.py                              # FastAPI Bootstrapper (< 100 lines)
```

---

## 💡 4. ข้อควรระวังและ Anti-Patterns ที่ห้ามทำ (Anti-Patterns to Avoid)

> [!CAUTION]
> **1. ห้ามสร้าง `utils.py` หรือ `common/helpers.py` กองรวมกันเป็นถังขยะ**
> หากต้องการเพิ่ม Utility ให้ถามว่าฟังก์ชันนั้นเป็นของใคร:
> - งานเกี่ยวกับ FFmpeg -> ใส่ใน `FFmpegAdapter`
> - งานเกี่ยวกับ Filesystem -> ใส่ใน `FilesystemAdapter`
> - Logic การคำนวณ Audio Chunk -> ใส่ใน `Transcription Domain/Application`

> [!IMPORTANT]
> **2. ป้องกัน Micro-File Explosion (Pragmatic Python)**
> ไม่ต้องสร้าง 1 File ต่อ 1 Class/Use Case ให้จับกลุ่ม Use Cases ที่เกี่ยวข้องกันไว้ในไฟล์ Cohesive Service เดียวกัน เช่น `transcription_service.py` หรือ `compression_service.py`

> [!WARNING]
> **3. Worker Subprocess Lazy Dependency Injection**
> ใน Worker Inbound Adapters ([`run_job.py`](file:///d:/_PROJECT_/choonova-transcribe/app/modules/transcription/adapters/inbound/workers/run_job.py) และ [`run_compress_job.py`](file:///d:/_PROJECT_/choonova-transcribe/app/modules/compression/adapters/inbound/workers/run_compress_job.py)) ต้องใช้ **Lazy Composition Root** ห้ามสั่ง top-level import PyTorch/NeMo ตั้งแต่ต้นไฟล์ เพื่อป้องกัน RAM/VRAM leak

> [!NOTE]
> **4. WebSocket Streaming Fast-Path**
> สำหรับ WebSocket Real-time Audio Stream ([`realtime_router.py`](file:///d:/_PROJECT_/choonova-transcribe/app/api/v1/realtime_router.py)) ให้ส่งผ่าน Audio Byte Chunks ตรงไปยัง ASR Engine โดยไม่ต้องผ่าน Full Database/Job Domain Entity Mapping ทุกๆ Chunk เพื่อรักษา Latency < 10ms

---

## 🧪 5. การสอบทานและ Testing (Verification Standards)

เมื่อสร้างหรือแก้ไขโค้ดใน Module ใดๆ ต้องสอบทานดังนี้เสมอ:
1. **Unit Testing (In-Memory Fake Repository)**:
   ```bash
   python -m unittest discover -s tests/unit
   ```
2. **Compilation Check**:
   ```bash
   python -m py_compile app/main.py
   ```
