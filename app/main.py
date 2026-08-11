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
    CLEANUP_RETENTION_HOURS,
    TARGET_CHUNK_DURATION_SEC,
    MAX_CHUNK_DURATION_SEC,
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
_active_workers: Dict[str, "subprocess.Popen"] = {}

# Track running video compressor subprocesses (FFmpeg jobs). The queue
# dispatcher enforces COMPRESS_MAX_CONCURRENT concurrent encodes by checking
# the size of this dict before spawning the next queued job.
_active_compress_workers: Dict[str, "subprocess.Popen"] = {}

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
            expired_ids = cleanup_expired_jobs(CLEANUP_RETENTION_HOURS)
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


@app.post("/v1/audio/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    with_timestamps: bool = Form(False),
    language: str = Form("th"),
    # Optional auth for API calls, skip if request comes from local dashboard
    authenticated: bool = Depends(verify_api_key),
):
    """
    Transcribe an uploaded audio file (WAV, MP3, M4A, OGG, FLAC).

    language: 'th' (default, Typhoon Thai ASR), 'en' (Whisper English), or
    'auto' (Whisper auto-detect for Thai/English mixed audio).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio file must be provided.")

    try:
        lang = normalize_language(language)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        # Stream read in 1MB chunks, enforcing the max upload size (always > 0).
        max_audio_bytes = int(MAX_AUDIO_UPLOAD_SIZE_MB * 1024 * 1024)
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > max_audio_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file exceeds maximum size of {MAX_AUDIO_UPLOAD_SIZE_MB:.0f} MB",
                )
        content = bytes(content)

        res = router_transcribe_bytes(
            audio_bytes=content,
            filename_hint=file.filename,
            language=lang,
            with_timestamps=with_timestamps,
        )

        text = res.get("text", "")
        elapsed = float(res.get("elapsed", 0.0))
        duration = float(res.get("duration", 0.0))
        timestamps = res.get("timestamps", [])

        rtf = elapsed / duration if duration > 0 else 0.0

        return TranscribeResponse(
            status="success",
            text=text,
            duration_seconds=round(duration, 2),
            elapsed_seconds=round(elapsed, 3),
            rtf=round(rtf, 5),
            timestamps=timestamps if with_timestamps else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during audio transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# Long-Form Media / Video Asynchronous Jobs API Endpoints
# =========================================================================


@app.post("/v1/media/transcribe/jobs", status_code=202, response_model=JobCreateResponse)
async def create_transcription_job(
    file: UploadFile = File(...),
    language: str = Form("th"),
    target_chunk_sec: float = Form(TARGET_CHUNK_DURATION_SEC),
    max_chunk_sec: float = Form(MAX_CHUNK_DURATION_SEC),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Upload a large video/audio file (MP4, MKV, MOV, WAV up to 1GB+) for long-form transcription.
    Returns job_id immediately with 202 Accepted status for async background processing.

    language: 'th' (default, Typhoon Thai ASR), 'en' (Whisper English), or
    'auto' (Whisper auto-detect for Thai/English mixed audio).

    target_chunk_sec / max_chunk_sec: chunk duration bounds for silence-based splitting.
    Defaults come from env (TARGET_CHUNK_DURATION_SEC / MAX_CHUNK_DURATION_SEC).
    """
    if not file.filename:
        raise HTTPException(
            status_code=400, detail="Video/Audio file must be provided."
        )

    if not (0 < target_chunk_sec <= max_chunk_sec):
        raise HTTPException(
            status_code=422,
            detail="target_chunk_sec must be greater than 0 and not exceed max_chunk_sec.",
        )

    try:
        lang = normalize_language(language)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free disk space is required.",
        )

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename)[1] or ".mp4"
    save_path = os.path.join(job_dir, f"input{file_ext}")

    # Stream file upload to disk in chunks of 1MB to prevent OOM.
    # Enforce max upload size (MB) when configured (> 0); 0 = unlimited.
    max_upload_bytes = int(MAX_UPLOAD_SIZE_MB * 1024 * 1024)
    total_bytes = 0
    try:
        with open(save_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if MAX_UPLOAD_SIZE_MB > 0 and total_bytes > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum upload size of {MAX_UPLOAD_SIZE_MB:.0f} MB",
                    )
                buffer.write(chunk)
    except HTTPException:
        safe_delete_dir(job_dir)
        raise
    except Exception as e:
        safe_delete_dir(job_dir)
        logger.error(f"Error saving upload file for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save upload file: {e}")

    # Insert job into SQLite
    create_job(
        job_id=job_id,
        filename=file.filename,
        file_size_bytes=total_bytes,
        language=lang,
        target_chunk_sec=target_chunk_sec,
        max_chunk_sec=max_chunk_sec,
    )

    # Launch worker in an isolated subprocess so GPU/CPU memory or errors never affect FastAPI web server
    import sys

    cmd = [sys.executable, "-m", "app.run_job", job_id, save_path, lang]
    proc = subprocess.Popen(cmd, cwd=SERVICE_DIR)
    _active_workers[job_id] = proc

    return JobCreateResponse(
        status="accepted",
        job_id=job_id,
        filename=file.filename,
        language=lang,
        message="Job created and enqueued for long-form video transcription",
    )


@app.get("/v1/media/transcribe/jobs", response_model=List[Dict[str, Any]])
async def list_transcription_jobs(
    limit: int = 50,
    include_text: bool = False,
    authenticated: bool = Depends(verify_api_key),
):
    """
    List recent transcription jobs ordered by creation date.
    By default excludes heavy text columns (result_text/srt_text/timestamps_json).
    Each row includes 'media_files_exist' indicating whether the media files are still on disk.
    """
    jobs = list_jobs(limit=limit)
    for job in jobs:
        job["media_files_exist"] = dir_has_files(
            os.path.join(TEMP_JOBS_DIR, job["job_id"])
        )
        if not include_text:
            job.pop("result_text", None)
            job.pop("srt_text", None)
            job.pop("timestamps_json", None)
    return jobs


@app.get("/v1/media/transcribe/jobs/{job_id}", response_model=JobStatusResponse)
async def get_transcription_job_status(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Get the status, stage, progress %, and completed transcript result of a job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return JobStatusResponse(**job)


@app.delete("/v1/media/transcribe/jobs/{job_id}")
async def cancel_transcription_job(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete a transcription job record from SQLite and clean up temporary disk files.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    # Terminate the worker subprocess so GPU/CPU resources are freed immediately
    # instead of the orphaned worker churning through remaining chunks.
    proc = _active_workers.pop(job_id, None)
    if proc is not None and proc.poll() is None:
        logger.info(f"Terminating worker subprocess for job {job_id} (cancel request)")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            logger.warning(f"Worker {job_id} did not exit after terminate; killing it")
            proc.kill()

    delete_job(job_id)
    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    safe_delete_dir(job_dir)
    return {"status": "success", "message": f"Job {job_id} deleted."}


@app.delete("/v1/media/transcribe/jobs/{job_id}/media")
async def delete_transcription_job_media(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete only the on-disk media files of a job (free machine resources)
    while KEEPING the transcription record (text/SRT/timestamps) in SQLite.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    if not dir_has_files(job_dir):
        return {
            "status": "success",
            "media_deleted": False,
            "message": "No media files found for this job (transcription record kept).",
        }

    safe_delete_dir(job_dir)
    if dir_has_files(job_dir):
        raise HTTPException(status_code=500, detail="Failed to delete media files.")

    return {
        "status": "success",
        "media_deleted": True,
        "message": "Media files deleted. Transcription record kept.",
    }


def _attachment_header(safe_name: str, ext: str) -> str:
    """Build an RFC 5987 Content-Disposition header that preserves UTF-8 (e.g. Thai)
    filenames. HTTP headers are latin-1 only, so the real name travels percent-encoded
    in `filename*=UTF-8''...` while `filename=` carries an ASCII-only fallback.
    """
    encoded = quote(safe_name, safe="")
    fallback = (
        re.sub(r"[^\x20-\x7e]", "_", safe_name).replace('"', "_").replace("\\", "_")
    )
    fallback = fallback or "transcript"
    return (
        f"attachment; filename=\"{fallback}.{ext}\"; filename*=UTF-8''{encoded}.{ext}"
    )


@app.get("/v1/media/transcribe/jobs/{job_id}/export/{export_format}")
async def export_job_result(
    job_id: str, export_format: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Download job transcription result as .txt, .srt subtitles, or .json timestamp format.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet.")

    export_format = export_format.lower()
    safe_name = os.path.splitext(job.get("filename", "transcript"))[0]

    if export_format == "txt":
        content = job.get("result_text") or ""
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(safe_name, "txt")},
        )
    elif export_format == "srt":
        content = job.get("srt_text") or ""
        return Response(
            content=content,
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(safe_name, "srt")},
        )
    elif export_format == "json":
        data = {
            "job_id": job["job_id"],
            "filename": job["filename"],
            "duration_seconds": job["duration_seconds"],
            "text": job.get("result_text"),
            "timestamps": job.get("timestamps"),
        }
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": _attachment_header(safe_name, "json")},
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported export format. Use 'txt', 'srt', or 'json'.",
        )


# =========================================================================
# Video Compressor (FFmpeg) Jobs API Endpoints
# =========================================================================


def compress_retention_summary() -> Dict[str, Any]:
    """
    Retention-policy info for the compressor dashboard: the configured window
    (COMPRESS_RETENTION_HOURS from env) and the last time the automatic
    cleanup actually removed on-disk files (tracked in the settings table).
    """
    last_at = get_setting("COMPRESS_LAST_CLEANUP_AT")
    try:
        last_count = int(get_setting("COMPRESS_LAST_CLEANUP_COUNT", "0") or 0)
    except (TypeError, ValueError):
        last_count = 0
    return {
        "retention_hours": COMPRESS_RETENTION_HOURS,
        "last_cleanup_at": last_at,
        "last_cleanup_count": last_count,
    }


def _validate_compress_params(
    target_width: int, bitrate_kbps: int, crf: int,
    trim_start: float = 0.0, trim_end: float = 0.0,
) -> None:
    """Validate compressor request parameters, raising HTTP 422 on invalid input."""
    if target_width < 0 or bitrate_kbps < 0:
        raise HTTPException(
            status_code=422, detail="target_width and bitrate_kbps must be >= 0."
        )
    if target_width == 0 and bitrate_kbps == 0:
        raise HTTPException(
            status_code=422,
            detail="Specify at least one of target_width (dimension) or bitrate_kbps "
            "(quality/bitrate) to compress the video.",
        )
    if not (1 <= crf <= 51):
        raise HTTPException(status_code=422, detail="crf must be between 1 and 51.")
    if target_width != 0 and target_width < 16:
        raise HTTPException(
            status_code=422, detail="target_width must be at least 16 px (or 0 to skip)."
        )
    if trim_start < 0 or trim_end < 0:
        raise HTTPException(
            status_code=422, detail="start and end must be >= 0 (0 = no trim)."
        )
    if trim_end > 0 and trim_start >= trim_end:
        raise HTTPException(
            status_code=422,
            detail="end must be greater than start when both are provided.",
        )


@app.post("/v1/media/compress/jobs", status_code=202, response_model=CompressJobCreateResponse)
async def create_compress_job_api(
    file: UploadFile = File(...),
    target_width: int = Form(0),
    bitrate_kbps: int = Form(0),
    crf: int = Form(COMPRESS_CRF),
    preset: str = Form(COMPRESS_PRESET),
    encoder: str = Form(COMPRESS_ENCODER),
    start: str = Form(""),
    end: str = Form(""),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Upload a video (MP4, MKV, MOV, ...) to compress in the background.

    - target_width > 0: rescale to this width keeping the aspect ratio (never upscales).
    - bitrate_kbps > 0: constrain the video bitrate (overrides CRF quality).
    - crf: encoder quality (higher = smaller file, 1-51, default 28).
    - preset: x264 preset (ultrafast..veryslow) or NVENC p1..p7 (auto-mapped).
    - encoder: 'libx264' (default) or 'nvenc' (GPU, if the ffmpeg build supports it).
    - start / end: optional trim window in 'SS', 'MM:SS' or 'HH:MM:SS' (seconds
      allowed too). Default (empty) = no trimming, the full video is kept.

    Only COMPRESS_MAX_CONCURRENT video(s) encode at once; uploads beyond
    COMPRESS_MAX_QUEUED are rejected with 429. Returns job_id immediately (202).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Video file must be provided.")

    try:
        trim_start = parse_trim_time(start)
        trim_end = parse_trim_time(end)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    _validate_compress_params(target_width, bitrate_kbps, crf, trim_start, trim_end)

    enc = normalize_encoder(encoder)

    queued = count_queued_compress_jobs()
    if queued >= COMPRESS_MAX_QUEUED:
        raise HTTPException(
            status_code=429,
            detail=f"Compression queue is full ({COMPRESS_MAX_QUEUED} jobs). "
            "Wait for pending jobs to finish and try again.",
        )

    if not check_disk_space(COMPRESS_OUTPUT_DIR, MIN_FREE_DISK_GB):
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free "
            "disk space is required.",
        )

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(COMPRESS_OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename)[1] or ".mp4"
    save_path = os.path.join(job_dir, f"input{file_ext}")

    max_upload_bytes = int(MAX_UPLOAD_SIZE_MB * 1024 * 1024)
    total_bytes = 0
    try:
        with open(save_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if MAX_UPLOAD_SIZE_MB > 0 and total_bytes > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum upload size of "
                        f"{MAX_UPLOAD_SIZE_MB:.0f} MB",
                    )
                buffer.write(chunk)
    except HTTPException:
        safe_delete_dir(job_dir)
        raise
    except Exception as e:
        safe_delete_dir(job_dir)
        logger.error(f"Error saving upload file for compress job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save upload file: {e}")

    create_compress_job(
        job_id=job_id,
        filename=file.filename,
        input_path=save_path,
        file_size_bytes=total_bytes,
        target_width=int(target_width or 0),
        bitrate_kbps=int(bitrate_kbps or 0),
        crf=int(crf or COMPRESS_CRF),
        preset=preset,
        encoder=enc,
        trim_start=trim_start,
        trim_end=trim_end,
    )

    qinfo = compress_job_queue_info(job_id)
    return CompressJobCreateResponse(
        status="accepted",
        job_id=job_id,
        filename=file.filename,
        queue_position=qinfo["queue_position"],
        queue_length=qinfo["queue_length"],
        message="Job created and enqueued for background video compression",
    )


@app.get("/v1/media/compress/jobs", response_model=List[Dict[str, Any]])
async def list_compress_jobs_api(
    limit: int = 50, authenticated: bool = Depends(verify_api_key)
):
    """
    List recent video compressor jobs ordered by creation date (newest first).
    """
    jobs = list_compress_jobs(limit=limit)
    for job in jobs:
        job.pop("input_path", None)
        job["output_exists"] = bool(
            job.get("output_path") and os.path.exists(job.get("output_path") or "")
        )
    return jobs


@app.get("/v1/media/compress/retention")
async def get_compress_retention_info(
    authenticated: bool = Depends(verify_api_key),
):
    """
    Retention-policy info for the compressor dashboard: how long compressed
    output files are kept on disk (COMPRESS_RETENTION_HOURS) and the timestamp
    + count of the last automatic cleanup that actually removed files.
    """
    return compress_retention_summary()


@app.get("/v1/media/compress/jobs/{job_id}", response_model=CompressJobStatusResponse)
async def get_compress_job_status(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Get the status, queue position, progress %, and result of a compressor job.
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")
    qinfo = compress_job_queue_info(job_id)
    job["queue_position"] = qinfo["queue_position"] if job["status"] == "queued" else 0
    job["queue_length"] = qinfo["queue_length"]
    return CompressJobStatusResponse(**job)


@app.delete("/v1/media/compress/jobs/{job_id}")
async def cancel_compress_job(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Cancel/delete a video compressor job: terminate the running FFmpeg worker,
    remove the job record, and delete ALL on-disk files (input + output).
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")

    proc = _active_compress_workers.pop(job_id, None)
    if proc is not None and proc.poll() is None:
        logger.info(f"Terminating compressor worker for job {job_id} (cancel request)")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            logger.warning(f"Compressor worker {job_id} did not exit after terminate; killing it")
            proc.kill()

    delete_compress_job(job_id)
    safe_delete_dir(os.path.join(COMPRESS_OUTPUT_DIR, job_id))
    return {
        "status": "success",
        "message": f"Compress job {job_id} deleted (input + output files removed).",
    }


@app.delete("/v1/media/compress/jobs/{job_id}/output")
async def delete_compress_job_output(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete ONLY the compressed output file of a completed job to free disk
    space, while keeping the job record (history) intact.
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")
    if job.get("status") != "completed" or not job.get("output_path"):
        raise HTTPException(status_code=400, detail="Job has no output file.")

    output_path = job["output_path"]
    base_real = os.path.realpath(COMPRESS_OUTPUT_DIR)
    job_dir_real = os.path.realpath(os.path.join(COMPRESS_OUTPUT_DIR, job_id))
    out_real = os.path.realpath(output_path)
    if not out_real.startswith(base_real + os.sep) or os.path.dirname(out_real) != job_dir_real:
        raise HTTPException(
            status_code=403, detail="Access to this output path is not allowed."
        )

    if not os.path.exists(out_real):
        return {
            "status": "success",
            "message": "Output file was already removed.",
            "output_size_bytes": job.get("output_size_bytes") or 0,
        }

    try:
        freed = os.path.getsize(out_real)
        os.remove(out_real)
    except OSError as e:
        logger.error(f"Failed to delete output file for compress job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete output file: {e}")

    logger.info(f"Compress job {job_id}: output file deleted manually (freed {freed} bytes)")
    return {
        "status": "success",
        "message": "Compressed output file deleted. Job record kept for history.",
        "output_size_bytes": freed,
    }


@app.get("/v1/media/compress/jobs/{job_id}/download")
async def download_compress_job(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Download the compressed MP4 output of a completed job. Returns 410 Gone if
    the output file has been cleaned up by the retention policy.
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")
    if job.get("status") != "completed" or not job.get("output_path"):
        raise HTTPException(status_code=400, detail="Job is not completed yet.")

    output_path = job["output_path"]
    if not os.path.exists(output_path):
        raise HTTPException(
            status_code=410,
            detail="Compressed file has been removed by the retention policy.",
        )

    # Path-safety: the output must live inside this job's own directory.
    base_real = os.path.realpath(COMPRESS_OUTPUT_DIR)
    job_dir_real = os.path.realpath(os.path.join(COMPRESS_OUTPUT_DIR, job_id))
    out_real = os.path.realpath(output_path)
    if not out_real.startswith(base_real + os.sep) or os.path.dirname(out_real) != job_dir_real:
        raise HTTPException(
            status_code=403, detail="Access to this output path is not allowed."
        )

    safe_name = os.path.splitext(job.get("filename", "video"))[0]
    response = FileResponse(out_real, media_type="video/mp4")
    response.headers["Content-Disposition"] = _attachment_header(safe_name, "mp4")
    return response


# =========================================================================
# WebSocket Real-Time Audio Streaming Endpoint
# =========================================================================


def remove_text_overlap(t1: str, t2: str) -> str:
    """
    Removes overlapping tail of t1 that matches the prefix of t2.
    Prevents duplicate words across streaming segment boundaries.
    """
    t1 = t1.strip()
    t2 = t2.strip()
    if not t1:
        return t2
    if not t2:
        return t1

    # Find longest suffix of t1 that matches prefix of t2
    max_check = min(len(t1), len(t2), 60)
    best_match_len = 0

    for length in range(3, max_check + 1):
        if t1[-length:] == t2[:length]:
            best_match_len = length

    if best_match_len > 0:
        suffix_added = t2[best_match_len:].strip()
        return (t1 + " " + suffix_added).strip()

    return (t1 + " " + t2).strip()


@app.websocket("/v1/realtime/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected for real-time speech transcription.")

    audio_buffer = io.BytesIO()
    header_bytes = b""  # Store initial WebM EBML header
    finalized_text = ""
    transcribe_lock = asyncio.Lock()
    MAX_BUFFER_BYTES = 480000  # ~15s limit

    async def _transcribe_bytes_async(b_data: bytes) -> str:
        if len(b_data) < 4096:
            return ""
        loop = asyncio.get_event_loop()
        # Two-tier CUDA recovery mirroring the long-form job worker:
        # - Tier 1 (transient driver error): backoff + clear_cuda_cache() + retry.
        # - Tier 2 (allocator corruption / illegal memory access): full CUDA
        #   device reset (cudaDeviceReset) + model reload, then one final retry.
        # Any residual failure degrades gracefully to "" so the WebSocket keeps
        # serving instead of letting a CUDA fault kill the whole process.
        for attempt in range(1, CUDA_RETRY_ATTEMPTS + 1):
            try:
                res = await loop.run_in_executor(
                    None, engine.transcribe_bytes, b_data, "stream.webm"
                )
                return res.get("text", "")
            except Exception as ex:
                if not is_cuda_error(ex):
                    logger.debug(f"Transcribe frame error (handled safely): {ex}")
                    return ""
                if is_allocator_corruption(ex):
                    logger.warning(
                        f"Realtime transcribe hit CUDA allocator corruption: {ex}; "
                        "performing full CUDA device reset + model reload before one final retry."
                    )
                    await loop.run_in_executor(None, cuda_device_reset_all)
                    try:
                        res = await loop.run_in_executor(
                            None, engine.transcribe_bytes, b_data, "stream.webm"
                        )
                        return res.get("text", "")
                    except Exception as ex2:
                        logger.debug(
                            f"Realtime transcribe retry failed (handled safely): {ex2}"
                        )
                        return ""
                if attempt == CUDA_RETRY_ATTEMPTS:
                    logger.warning(
                        f"Realtime transcribe failed {attempt} attempts with CUDA error: {ex}; "
                        "reloading model and retrying once more"
                    )
                    await loop.run_in_executor(None, reset_all)
                    await loop.run_in_executor(None, engine.clear_cuda_cache)
                    try:
                        res = await loop.run_in_executor(
                            None, engine.transcribe_bytes, b_data, "stream.webm"
                        )
                        return res.get("text", "")
                    except Exception as ex2:
                        logger.debug(
                            f"Realtime transcribe retry failed (handled safely): {ex2}"
                        )
                        return ""
                backoff = CUDA_RETRY_BACKOFF_SEC * attempt
                logger.warning(
                    f"Realtime transcribe CUDA error "
                    f"(attempt {attempt}/{CUDA_RETRY_ATTEMPTS}): {ex}; "
                    f"retrying in {backoff:.0f}s"
                )
                await loop.run_in_executor(None, engine.clear_cuda_cache)
                await asyncio.sleep(backoff)
        return ""

    try:
        while True:
            msg = await websocket.receive()
            if "bytes" in msg and msg["bytes"]:
                chunk = msg["bytes"]
                if not header_bytes:
                    header_bytes = chunk[:1024]
                audio_buffer.write(chunk)

                if audio_buffer.tell() > MAX_BUFFER_BYTES:
                    raw = audio_buffer.getvalue()
                    audio_buffer = io.BytesIO()
                    audio_buffer.write(header_bytes)
                    audio_buffer.write(raw[-MAX_BUFFER_BYTES:])

            elif "text" in msg:
                cmd = msg["text"].strip()
                if cmd == "CLEAR":
                    async with transcribe_lock:
                        finalized_text = ""
                        audio_buffer = io.BytesIO()
                        if header_bytes:
                            audio_buffer.write(header_bytes)

                elif cmd == "COMMIT_SEGMENT":
                    async with transcribe_lock:
                        b_data = audio_buffer.getvalue()
                        # Clean buffer completely for next segment
                        audio_buffer = io.BytesIO()
                        if header_bytes:
                            audio_buffer.write(header_bytes)

                        if len(b_data) > 4096:
                            text = await _transcribe_bytes_async(b_data)
                            if text:
                                finalized_text = remove_text_overlap(
                                    finalized_text, text
                                )
                            await websocket.send_json(
                                {
                                    "type": "final",
                                    "text": text,
                                    "fullText": finalized_text,
                                }
                            )

                elif cmd == "INTERIM":
                    if not transcribe_lock.locked():
                        async with transcribe_lock:
                            b_data = audio_buffer.getvalue()
                            if len(b_data) > 4096:
                                text = await _transcribe_bytes_async(b_data)
                                if text:
                                    preview = remove_text_overlap(finalized_text, text)
                                    await websocket.send_json(
                                        {
                                            "type": "partial",
                                            "text": text,
                                            "fullText": preview,
                                        }
                                    )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
