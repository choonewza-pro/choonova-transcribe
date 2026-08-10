import os
import io
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
from fastapi.responses import HTMLResponse, JSONResponse, Response, PlainTextResponse
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
)
from app.auth import verify_api_key
from app.schemas import (
    TranscribeResponse,
    HealthResponse,
    JobCreateResponse,
    JobStatusResponse,
    JobListItem,
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
)
from app.audio_utils import check_disk_space, safe_delete_dir
from app.job_worker import process_transcription_job
from app.asr_engine import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("typhoon-asr-main")

# Track isolated worker subprocesses so the watchdog can detect crashes
# that bypass Python exception handling (e.g. C++ std::terminate from
# PyTorch/CUDA illegal memory access). Without this, a crashed worker
# leaves its job row stuck in 'transcribing' forever.
_active_workers: Dict[str, "subprocess.Popen"] = {}

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
    """
    while True:
        try:
            await asyncio.sleep(3600)
            expired_ids = cleanup_expired_jobs(CLEANUP_RETENTION_HOURS)
            for j_id in expired_ids:
                j_dir = os.path.join(TEMP_JOBS_DIR, j_id)
                safe_delete_dir(j_dir)
        except Exception as e:
            logger.error(f"Error in periodic_cleanup_task: {e}")


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


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting Typhoon ASR Service on {HOST}:{PORT} (Device: {DEVICE})...")
    # Initialize SQLite database and recover zombie jobs
    init_db()
    recover_zombie_jobs()
    # Start periodic 24-hour retention cleanup worker
    asyncio.create_task(periodic_cleanup_task())
    # Start worker crash watchdog (detects subprocess crashes that bypass
    # Python exception handling, e.g. CUDA illegal memory access)
    asyncio.create_task(watchdog_workers())

    try:
        engine.load_model()
    except Exception as e:
        logger.warning(f"Engine lazy loading deferred: {e}")


# =========================================================================
# UI Dashboard Routes (HTML Pages)
# =========================================================================


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/test/upload", response_class=HTMLResponse)
async def test_upload_page(request: Request):
    return templates.TemplateResponse(request=request, name="upload.html")


@app.get("/test/realtime", response_class=HTMLResponse)
async def test_realtime_page(request: Request):
    return templates.TemplateResponse(request=request, name="realtime.html")


@app.get("/test/media", response_class=HTMLResponse)
async def test_media_page(request: Request):
    return templates.TemplateResponse(request=request, name="media.html")


@app.get("/test/jobs", response_class=HTMLResponse)
async def test_jobs_page(request: Request):
    return templates.TemplateResponse(request=request, name="jobs.html")


# =========================================================================
# API Endpoints
# =========================================================================


@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", service="typhoon-asr-service", device=DEVICE)


@app.post("/v1/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    with_timestamps: bool = Form(False),
    # Optional auth for API calls, skip if request comes from local dashboard
    authenticated: bool = Depends(verify_api_key),
):
    """
    Transcribe an uploaded audio file (WAV, MP3, M4A, OGG, FLAC) to Thai text.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio file must be provided.")

    try:
        content = await file.read()
        res = engine.transcribe_bytes(
            audio_bytes=content,
            filename_hint=file.filename,
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
    except Exception as e:
        logger.error(f"Error during audio transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# Long-Form Media / Video Asynchronous Jobs API Endpoints
# =========================================================================


@app.post("/v1/transcribe/jobs", status_code=202, response_model=JobCreateResponse)
async def create_transcription_job(
    file: UploadFile = File(...), authenticated: bool = Depends(verify_api_key)
):
    """
    Upload a large video/audio file (MP4, MKV, MOV, WAV up to 1GB+) for long-form transcription.
    Returns job_id immediately with 202 Accepted status for async background processing.
    """
    if not file.filename:
        raise HTTPException(
            status_code=400, detail="Video/Audio file must be provided."
        )

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

    # Stream file upload to disk in chunks of 1MB to prevent OOM
    total_bytes = 0
    try:
        with open(save_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
                total_bytes += len(chunk)
    except Exception as e:
        safe_delete_dir(job_dir)
        logger.error(f"Error saving upload file for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save upload file: {e}")

    # Insert job into SQLite
    create_job(job_id=job_id, filename=file.filename, file_size_bytes=total_bytes)

    # Launch worker in an isolated subprocess so GPU/CPU memory or errors never affect FastAPI web server
    import sys

    cmd = [sys.executable, "-m", "app.run_job", job_id, save_path]
    proc = subprocess.Popen(cmd, cwd=SERVICE_DIR)
    _active_workers[job_id] = proc

    return JobCreateResponse(
        status="accepted",
        job_id=job_id,
        filename=file.filename,
        message="Job created and enqueued for long-form video transcription",
    )


@app.get("/v1/transcribe/jobs", response_model=List[Dict[str, Any]])
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


@app.get("/v1/transcribe/jobs/{job_id}", response_model=JobStatusResponse)
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


@app.delete("/v1/transcribe/jobs/{job_id}")
async def cancel_transcription_job(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete a transcription job record from SQLite and clean up temporary disk files.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    delete_job(job_id)
    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    safe_delete_dir(job_dir)
    return {"status": "success", "message": f"Job {job_id} deleted."}


@app.delete("/v1/transcribe/jobs/{job_id}/media")
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


@app.get("/v1/transcribe/jobs/{job_id}/export/{export_format}")
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


@app.websocket("/v1/stream")
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
        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, engine.transcribe_bytes, b_data, "stream.webm"
            )
            return res.get("text", "")
        except Exception as ex:
            logger.debug(f"Transcribe frame error (handled safely): {ex}")
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
