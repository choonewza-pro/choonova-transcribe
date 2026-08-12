
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import os
import uuid
import subprocess
import re
from urllib.parse import quote

from app.core.security import verify_api_key
from app.core.state import _active_workers
from app.core.media_validator import validate_magic_bytes, validate_extension, validate_with_ffprobe, secure_filename
from app.config import (
    MAX_AUDIO_UPLOAD_SIZE_MB, MAX_UPLOAD_SIZE_MB, 
    TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC, TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC,
    TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC, TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC,
    TEMP_JOBS_DIR, MIN_FREE_DISK_GB, SERVICE_DIR
)
from app.schemas import TranscribeResponse, JobCreateResponse, JobStatusResponse
from app.engine_router import normalize_language, transcribe_bytes as router_transcribe_bytes
from app.audio_utils import check_disk_space, safe_delete_dir
from app.db import create_job, get_job, list_jobs, delete_job
import logging

logger = logging.getLogger("typhoon-asr-transcription")

router = APIRouter(tags=["Transcription"])

def dir_has_files(dir_path: str) -> bool:
    try:
        if os.path.isdir(dir_path):
            with os.scandir(dir_path) as it:
                return any(it)
    except Exception:
        pass
    return False

@router.post("/v1/audio/transcribe", response_model=TranscribeResponse)
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

    validate_extension(file.filename)

    try:
        lang = normalize_language(language)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free disk space is required.",
        )

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
        validate_magic_bytes(content[:2048])

        res = router_transcribe_bytes(
            audio_bytes=content,
            filename_hint=secure_filename(file.filename),
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


@router.post("/v1/media/transcribe/jobs", status_code=202, response_model=JobCreateResponse)
async def create_transcription_job(
    file: UploadFile = File(...),
    language: str = Form("th"),
    target_chunk_sec: float = Form(None),
    max_chunk_sec: float = Form(None),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Upload a large video/audio file (MP4, MKV, MOV, WAV up to 1GB+) for long-form transcription.
    Returns job_id immediately with 202 Accepted status for async background processing.

    language: 'th' (default, Typhoon Thai ASR), 'en' (Whisper English), or
    'auto' (Whisper auto-detect for Thai/English mixed audio).

    target_chunk_sec / max_chunk_sec: chunk duration bounds for silence-based splitting.
    Defaults come from env based on the selected language model.
    """
    if not file.filename:
        raise HTTPException(
            status_code=400, detail="Video/Audio file must be provided."
        )

    validate_extension(file.filename)

    try:
        lang = normalize_language(language)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
        
    if target_chunk_sec is None or max_chunk_sec is None:
        if lang == "th":
            target_chunk_sec = target_chunk_sec or TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC
            max_chunk_sec = max_chunk_sec or TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC
        else:
            target_chunk_sec = target_chunk_sec or TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC
            max_chunk_sec = max_chunk_sec or TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC

    if not (0 < target_chunk_sec <= max_chunk_sec):
        raise HTTPException(
            status_code=422,
            detail="target_chunk_sec must be greater than 0 and not exceed max_chunk_sec.",
        )

    if not check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free disk space is required.",
        )

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    safe_name = secure_filename(file.filename)
    file_ext = os.path.splitext(safe_name)[1] or ".mp4"
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

    # Validate Magic Bytes and FFprobe for saved file
    try:
        with open(save_path, "rb") as f:
            header_bytes = f.read(2048)
        validate_magic_bytes(header_bytes)
        validate_with_ffprobe(save_path)
    except HTTPException:
        safe_delete_dir(job_dir)
        raise
    except Exception as e:
        safe_delete_dir(job_dir)
        logger.error(f"Validation error for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate media file")

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


@router.get("/v1/media/transcribe/jobs", response_model=List[Dict[str, Any]])
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


@router.get("/v1/media/transcribe/jobs/{job_id}", response_model=JobStatusResponse)
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


@router.delete("/v1/media/transcribe/jobs/{job_id}")
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


@router.delete("/v1/media/transcribe/jobs/{job_id}/media")
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


@router.get("/v1/media/transcribe/jobs/{job_id}/export/{export_format}")
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
