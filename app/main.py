import os
import io
import sys
import time
import uuid
import asyncio
import tempfile
import re
import logging
import subprocess
from urllib.parse import quote
from typing import List, Dict, Any

from fastapi import (
    FastAPI,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
)
from app.core.media_validator import (
    validate_magic_bytes,
    validate_extension,
    validate_with_ffprobe,
    secure_filename
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, Response, PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    HOST,
    PORT,
    DEVICE,
    GATEWAY_API_KEY,
    LOG_LEVEL,
    SERVICE_DIR,
    TEMP_JOBS_DIR,
    MIN_FREE_DISK_GB,
    TRANSCRIBE_RETENTION_HOURS,

    MAX_UPLOAD_SIZE_MB,
    MAX_AUDIO_UPLOAD_SIZE_MB,
    COMPRESS_ENCODER,
    COMPRESS_PRESET,
    COMPRESS_CRF,
    COMPRESS_MAX_CONCURRENT,
    COMPRESS_MAX_QUEUED,
    COMPRESS_RETENTION_HOURS,
    COMPRESS_OUTPUT_DIR,
)
from app.auth import verify_api_key
from app.schemas import (
    TranscribeResponse,
    HealthResponse,
    JobCreateResponse,
    JobStatusResponse,
    JobListItem,
    ModelSettings,
    ModelSettingsResponse,
    CompressJobCreateResponse,
    CompressJobStatusResponse,
)
from app.db import (
    init_db,
    recover_zombie_jobs,
    create_job,
    get_job,
    list_jobs,
    delete_job,
    cleanup_expired_jobs,
    update_job_status,
    get_setting,
    set_setting,
    create_compress_job,
    get_compress_job,
    list_compress_jobs,
    delete_compress_job,
    update_compress_job,
    get_next_queued_compress_job,
    count_queued_compress_jobs,
    compress_job_queue_info,
    recover_zombie_compress_jobs,
    cleanup_expired_compress_jobs,
)
from app.audio_utils import check_disk_space, safe_delete_dir
from app.cuda_utils import is_cuda_error, is_allocator_corruption
from app.compress_utils import normalize_encoder, parse_trim_time
from app.core.state import _active_workers, _active_compress_workers
from app.job_worker import (
    process_transcription_job,
    CUDA_RETRY_ATTEMPTS,
    CUDA_RETRY_BACKOFF_SEC,
)
from app.asr_engine import engine
from app.engine_router import (
    transcribe_bytes as router_transcribe_bytes,
    reset_all,
    cuda_device_reset_all,
    normalize_language,
    get_engines_state,
    apply_model_mode,
    unload_if_idle_all,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("typhoon-asr-main")

# Track isolated worker subprocesses so the watchdog can detect crashes
# that bypass Python exception handling (e.g. C++ std::terminate from
# PyTorch/CUDA illegal memory access). Without this, a crashed worker
# leaves its job row stuck in 'transcribing' forever.


# Track running video compressor subprocesses (FFmpeg jobs). The queue
# dispatcher enforces COMPRESS_MAX_CONCURRENT concurrent encodes by checking
# the size of this dict before spawning the next queued job.


# When the watchdog detects a crashed worker (returncode != 0 while the DB row
# is still in a processing state), optionally delete the job's on-disk files
# (input media, extracted audio, chunks). Default false to preserve forensic
# evidence for debugging; enable in production once the service is stable.
# Note: the DB record + error_message are always kept regardless of this flag.
WATCHDOG_DELETE_ON_CRASH = os.getenv("WATCHDOG_DELETE_ON_CRASH", "false").lower() in (
    "1",
    "true",
    "yes",
)

app = FastAPI(
    title="Typhoon ASR Realtime API Service",
    description="Speech-to-Text API Service powered by Typhoon ASR Realtime model (114M parameters)",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Mount Static Files & Templates
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Mount Modular Hexagonal Routers
from app.api.v1.settings_router import router as settings_router
from app.api.v1.compression_router import router as compression_router
from app.api.v1.transcription_router import router as transcription_router
from app.api.v1.realtime_router import router as realtime_router
from app.api.web.views_router import router as views_router

app.include_router(settings_router)
app.include_router(compression_router)
app.include_router(transcription_router)
app.include_router(realtime_router)
app.include_router(views_router)



def dir_has_files(dir_path: str) -> bool:
    """
    Return True if the directory exists and contains at least one entry.
    """
    try:
        if os.path.isdir(dir_path):
            with os.scandir(dir_path) as it:
                return any(it)
    except Exception as e:
        logger.warning(f"Failed to scan directory {dir_path}: {e}")
    return False


async def periodic_cleanup_task():
    """
    Periodic background task running every 1 hour to clean up jobs > 24 hours old.
    Also removes expired video compressor output files (COMPRESS_RETENTION_HOURS).
    """
    while True:
        try:
            await asyncio.sleep(3600)
            expired_ids = cleanup_expired_jobs(TRANSCRIBE_RETENTION_HOURS)
            for j_id in expired_ids:
                j_dir = os.path.join(TEMP_JOBS_DIR, j_id)
                safe_delete_dir(j_dir)
            expired_compress_ids = cleanup_expired_compress_jobs(COMPRESS_RETENTION_HOURS)
            for c_id in expired_compress_ids:
                safe_delete_dir(os.path.join(COMPRESS_OUTPUT_DIR, c_id))
        except Exception as e:
            logger.error(f"Error in periodic_cleanup_task: {e}")


def current_model_load_mode() -> str:
    """
    Runtime model residency mode from the settings DB (seeded from env on first boot).
    """
    return (get_setting("MODEL_LOAD_MODE", "always") or "always").strip().lower()


def current_idle_timeout_sec() -> float:
    """
    Runtime idle timeout (seconds) from the settings DB (seeded from env on first boot).
    """
    try:
        return float(get_setting("MODEL_IDLE_TIMEOUT_SEC", "900") or "900")
    except (TypeError, ValueError):
        return 900.0


async def model_idle_reaper():
    """
    Unload models from VRAM after a configurable idle period in 'idle' mode.

    The mode/timeout are read from the settings DB on every cycle, so switching
    between 'always' and 'idle' via the dashboard/API takes effect without a
    restart. No-ops (cheaply) while in 'always' mode.
    """
    while True:
        try:
            if current_model_load_mode() == "idle":
                timeout = current_idle_timeout_sec()
                loop = asyncio.get_running_loop()
                unloaded = await loop.run_in_executor(None, unload_if_idle_all, timeout)
                if unloaded:
                    logger.info("Model idle reaper unloaded one or more models")
                await asyncio.sleep(max(30.0, timeout / 4.0))
            else:
                await asyncio.sleep(30.0)
        except Exception as e:
            logger.error(f"Error in model_idle_reaper: {e}")
            await asyncio.sleep(30.0)


async def watchdog_workers():
    """
    Detect worker subprocesses that died (crashed, OOM-killed, or hit C++
    std::terminate from CUDA illegal memory access) without ever writing a
    final status to the DB. Such jobs would otherwise stay 'transcribing'
    forever (zombie jobs) until the next server restart.

    Runs every 30s. For each tracked Popen that has exited, if the DB row
    is still in a non-terminal state, mark it failed and drop the handle.
    """
    while True:
        try:
            await asyncio.sleep(30)
            for job_id, proc in list(_active_workers.items()):
                if proc.poll() is None:
                    continue  # still running
                # Process has ended — inspect DB state
                try:
                    job = get_job(job_id)
                except Exception as e:
                    logger.warning(f"Watchdog: failed to query job {job_id}: {e}")
                    _active_workers.pop(job_id, None)
                    continue
                if job and job.get("status") in (
                    "queued",
                    "extracting",
                    "chunking",
                    "transcribing",
                ):
                    update_job_status(
                        job_id,
                        status="failed",
                        current_stage="Failed",
                        error_message=(
                            f"Worker process crashed (exit code {proc.returncode}) "
                            "before completing; likely a CUDA illegal memory access "
                            "or other native fault that bypassed Python exception handling"
                        ),
                    )
                    logger.error(
                        f"Watchdog: job {job_id} worker died (exit={proc.returncode}); "
                        "DB row was still in processing state, marked failed"
                    )
                    # Only delete on-disk files for a genuine crash (exit code != 0).
                    # Skipping when exit==0 guards against the rare case where the
                    # worker finished but the final DB update hadn't been written yet.
                    if proc.returncode != 0 and WATCHDOG_DELETE_ON_CRASH:
                        safe_delete_dir(os.path.join(TEMP_JOBS_DIR, job_id))
                        logger.info(
                            f"Watchdog: removed job dir for crashed job {job_id}"
                        )
                _active_workers.pop(job_id, None)
        except Exception as e:
            logger.error(f"Error in watchdog_workers: {e}")


async def compress_queue_dispatcher():
    """
    FIFO queue dispatcher for video compressor jobs.

    Polls SQLite for the oldest 'queued' job and spawns an isolated worker
    subprocess for it, but never runs more than COMPRESS_MAX_CONCURRENT encodes
    at once (the strict single-file queue is COMPRESS_MAX_CONCURRENT=1). The
    worker updates progress in the DB; a watcher task cleans up the handle when
    the subprocess exits and marks the job failed if no terminal state was written.
    """
    while True:
        try:
            await asyncio.sleep(1)
            if len(_active_compress_workers) >= COMPRESS_MAX_CONCURRENT:
                continue

            job = get_next_queued_compress_job()
            if not job:
                continue
            job_id = job["job_id"]
            if job_id in _active_compress_workers:
                continue

            input_path = job.get("input_path")
            if not input_path or not os.path.exists(input_path):
                logger.warning(
                    f"Compress job {job_id} has no input file on disk; marking failed"
                )
                update_compress_job(
                    job_id, status="failed", current_stage="Failed",
                    error_message="Input file missing before processing started",
                )
                safe_delete_dir(os.path.join(COMPRESS_OUTPUT_DIR, job_id))
                continue

            # Mark as processing and spawn the isolated worker.
            update_compress_job(
                job_id, status="processing", progress_pct=0.5,
                current_stage="Spawning FFmpeg worker",
            )
            cmd = [
                sys.executable, "-m", "app.run_compress_job",
                job_id,
                input_path,
                str(int(job.get("target_width") or 0)),
                str(int(job.get("bitrate_kbps") or 0)),
                str(int(job.get("crf") or 28)),
                job.get("preset") or "medium",
                job.get("encoder") or "libx264",
                str(float(job.get("trim_start") or 0.0)),
                str(float(job.get("trim_end") or 0.0)),
                job.get("audio_extract_format") or "",
            ]
            logger.info(f"Starting compressor worker for job {job_id}")
            proc = subprocess.Popen(cmd, cwd=SERVICE_DIR)
            _active_compress_workers[job_id] = proc
            asyncio.create_task(watch_compress_process(job_id, proc))
        except Exception as e:
            logger.error(f"Error in compress_queue_dispatcher: {e}")


async def watch_compress_process(job_id: str, proc: "subprocess.Popen"):
    """
    Watches a running compressor subprocess. On exit, if the DB row is still in
    'processing' (worker crashed without writing a terminal state, was killed,
    or exited before completing), mark it failed. On normal completion the worker
    already wrote 'completed', so this is a no-op.
    """
    try:
        await asyncio.to_thread(proc.wait)
    finally:
        _active_compress_workers.pop(job_id, None)
        try:
            job = get_compress_job(job_id)
            if job and job.get("status") == "processing":
                update_compress_job(
                    job_id,
                    status="failed",
                    current_stage="Failed",
                    error_message=(
                        f"Compressor worker process exited unexpectedly "
                        f"(code {proc.returncode})"
                    ),
                )
                logger.error(
                    f"Compressor worker for job {job_id} died "
                    f"(exit={proc.returncode}); DB row still in processing, marked failed"
                )
        except Exception as e:
            logger.warning(f"watch_compress_process failed for {job_id}: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting Typhoon ASR Service on {HOST}:{PORT} (Device: {DEVICE})...")
    # Initialize SQLite database and recover zombie jobs (also seeds the
    # settings table with MODEL_LOAD_MODE / MODEL_IDLE_TIMEOUT_SEC from env).
    init_db()
    recover_zombie_jobs()
    # Recover video compressor jobs interrupted by a previous shutdown/crash and
    # delete their leftover job directories (they can still hold a large input).
    recovered_compress = recover_zombie_compress_jobs()
    for c_id in recovered_compress:
        safe_delete_dir(os.path.join(COMPRESS_OUTPUT_DIR, c_id))
    # Start periodic 24-hour retention cleanup worker
    asyncio.create_task(periodic_cleanup_task())
    # Start worker crash watchdog (detects subprocess crashes that bypass
    # Python exception handling, e.g. CUDA illegal memory access)
    asyncio.create_task(watchdog_workers())
    # Start the model VRAM idle reaper (active only in 'idle' mode)
    asyncio.create_task(model_idle_reaper())
    # Start the video compressor queue dispatcher (FIFO, 1+ concurrent encodes)
    asyncio.create_task(compress_queue_dispatcher())

    mode = current_model_load_mode()
    if mode == "always":
        # Warm Typhoon model at boot (original behavior); Whisper loads lazily.
        try:
            engine.load_model()
        except Exception as e:
            logger.warning(f"Engine lazy loading deferred: {e}")
    else:
        logger.info(
            f"Model load mode is '{mode}' — skipping eager model load; "
            "models will load on demand"
        )


# =========================================================================
# UI Dashboard Routes (HTML Pages)
# =========================================================================


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"max_audio_upload_mb": MAX_AUDIO_UPLOAD_SIZE_MB},
    )


@app.get("/audio/transcribe", response_class=HTMLResponse)
async def audio_transcribe_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"max_audio_upload_mb": MAX_AUDIO_UPLOAD_SIZE_MB},
    )


@app.get("/realtime/stream", response_class=HTMLResponse)
async def realtime_stream_page(request: Request):
    return templates.TemplateResponse(request=request, name="realtime.html")


@app.get("/media/transcribe", response_class=HTMLResponse)
async def media_transcribe_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="media.html",
        context={"max_upload_mb": MAX_UPLOAD_SIZE_MB},
    )


@app.get("/media/compress", response_class=HTMLResponse)
async def media_compress_page(request: Request):
    retention = compress_retention_summary()
    return templates.TemplateResponse(
        request=request,
        name="compress.html",
        context={
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
            "default_crf": COMPRESS_CRF,
            "default_preset": COMPRESS_PRESET,
            "encoder": COMPRESS_ENCODER,
            "device": DEVICE,
            "max_concurrent": COMPRESS_MAX_CONCURRENT,
            "max_queued": COMPRESS_MAX_QUEUED,
            "retention_hours": retention["retention_hours"],
            "last_cleanup_at": retention["last_cleanup_at"],
            "last_cleanup_count": retention["last_cleanup_count"],
        },
    )


@app.get("/media/compress/jobs/history", response_class=HTMLResponse)
async def compress_jobs_history_page(request: Request):
    retention = compress_retention_summary()
    return templates.TemplateResponse(
        request=request,
        name="compress_jobs.html",
        context={
            "active_page": "compress_jobs",
            "header_badge": "Compressor History",
            "retention_hours": retention["retention_hours"],
            "last_cleanup_at": retention["last_cleanup_at"],
            "last_cleanup_count": retention["last_cleanup_count"],
        },
    )


@app.get("/media/transcribe/jobs/history", response_class=HTMLResponse)
async def jobs_history_page(request: Request):
    return templates.TemplateResponse(request=request, name="jobs.html")


@app.get("/setting", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="setting.html")


@app.get("/jobs/history", response_class=HTMLResponse)
async def jobs_history_page_legacy(request: Request):
    return RedirectResponse(url="/media/transcribe/jobs/history", status_code=302)


# =========================================================================
# API Endpoints
# =========================================================================


@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    states = get_engines_state()
    return HealthResponse(
        status="ok",
        service="typhoon-asr-service",
        device=DEVICE,
        model_load_mode=current_model_load_mode(),
        model_idle_timeout_sec=current_idle_timeout_sec(),
        typhoon_model_state=states["typhoon"],
        whisper_model_state=states["whisper"],
    )


# =========================================================================
# Runtime Settings Endpoints (model VRAM residency mode)
# =========================================================================


@app.get("/v1/settings/model", response_model=ModelSettingsResponse)
async def get_model_settings(authenticated: bool = Depends(verify_api_key)):
    """Get the current model residency mode, idle timeout, and engine states."""
    states = get_engines_state()
    return ModelSettingsResponse(
        mode=current_model_load_mode(),
        idle_timeout_sec=current_idle_timeout_sec(),
        typhoon_model_state=states["typhoon"],
        whisper_model_state=states["whisper"],
    )


@app.put("/v1/settings/model", response_model=ModelSettingsResponse)
async def update_model_settings(
    payload: ModelSettings, authenticated: bool = Depends(verify_api_key)
):
    """
    Change the model residency mode at runtime (no restart required).

    mode:
      - 'always': models stay resident in VRAM (warm). Eagerly loads engines now.
      - 'idle':   models are unloaded after idle_timeout_sec of inactivity.
    """
    mode = payload.mode
    timeout = payload.idle_timeout_sec

    set_setting("MODEL_LOAD_MODE", mode)
    set_setting("MODEL_IDLE_TIMEOUT_SEC", str(timeout))
    logger.info(
        f"Model load mode changed to '{mode}' (idle_timeout={timeout:.0f}s) via API"
    )

    try:
        states = apply_model_mode(mode)
    except Exception as e:
        # Settings are already persisted; if eager loading fails (e.g. model
        # unavailable), the badge shows it and the next request lazy-loads.
        logger.error(f"apply_model_mode failed after saving settings: {e}")
        states = get_engines_state()

    return ModelSettingsResponse(
        mode=mode,
        idle_timeout_sec=timeout,
        typhoon_model_state=states["typhoon"],
        whisper_model_state=states["whisper"],
    )


