
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import uuid
import subprocess

from app.core.security import verify_api_key
from app.core.state import _active_compress_workers
from app.core.media_validator import validate_magic_bytes, validate_extension, validate_with_ffprobe, secure_filename
from app.config import (
    MAX_UPLOAD_SIZE_MB, COMPRESS_CRF, COMPRESS_PRESET, COMPRESS_ENCODER,
    COMPRESS_MAX_QUEUED, MIN_FREE_DISK_GB, COMPRESS_OUTPUT_DIR
)
from app.schemas import CompressJobCreateResponse, CompressJobStatusResponse
from app.compress_utils import normalize_encoder, parse_trim_time
from app.audio_utils import check_disk_space, safe_delete_dir
from app.db import (
    create_compress_job, get_compress_job, list_compress_jobs, delete_compress_job, update_compress_job,
    compress_job_queue_info, get_compress_retention_summary
)
import logging
logger = logging.getLogger("typhoon-asr-compress")

router = APIRouter(tags=["Compression"])

def _attachment_header(safe_name: str, ext: str) -> str:
    import re
    from urllib.parse import quote
    encoded = quote(safe_name, safe="")
    fallback = re.sub(r"[^ -~]", "_", safe_name).replace('"', "_").replace("\\", "_")
    fallback = fallback or "video"
    return f"attachment; filename=\"{fallback}.{ext}\"; filename*=UTF-8''{encoded}.{ext}"

# Video Compressor (FFmpeg) Jobs API Endpoints
# =========================================================================


def compress_retention_summary() -> Dict[str, Any]:
    """
    Retention-policy info for the compressor dashboard: the configured window
    (COMPRESS_RETENTION_HOURS from env) and the last time the automatic
    cleanup actually removed on-disk files (tracked in the settings table).
    """
    from app.db import get_compress_retention_summary
    return get_compress_retention_summary()


def _validate_compress_params(
    target_width: int, bitrate_kbps: int, crf: int,
    trim_start: float = 0.0, trim_end: float = 0.0,
) -> None:
    """Validate compressor request parameters, raising HTTP 422 on invalid input."""
    if target_width < 0 or bitrate_kbps < 0:
        raise HTTPException(
            status_code=422, detail="target_width and bitrate_kbps must be >= 0."
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


@router.post("/v1/media/compress/jobs", status_code=202, response_model=CompressJobCreateResponse)
async def create_compress_job_api(
    file: UploadFile = File(...),
    target_width: int = Form(0),
    bitrate_kbps: int = Form(0),
    crf: int = Form(COMPRESS_CRF),
    preset: str = Form(COMPRESS_PRESET),
    encoder: str = Form(COMPRESS_ENCODER),
    start: str = Form(""),
    end: str = Form(""),
    audio_extract: str = Form(""),
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
    - audio_extract: '' (none, default), 'wav' (16kHz mono PCM) or 'mp3' (192kbps).

    Only COMPRESS_MAX_CONCURRENT video(s) encode at once; uploads beyond
    COMPRESS_MAX_QUEUED are rejected with 429. Returns job_id immediately (202).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Video file must be provided.")

    validate_extension(file.filename)

    try:
        trim_start = parse_trim_time(start)
        trim_end = parse_trim_time(end)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    _validate_compress_params(target_width, bitrate_kbps, crf, trim_start, trim_end)

    enc = normalize_encoder(encoder)

    if audio_extract not in ("", "wav", "mp3"):
        raise HTTPException(
            status_code=422,
            detail="audio_extract must be '', 'wav', or 'mp3'.",
        )

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

    safe_name = secure_filename(file.filename)
    file_ext = os.path.splitext(safe_name)[1] or ".mp4"
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
        logger.error(f"Validation error for compress job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate media file")

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
        audio_extract_format=audio_extract,
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


@router.get("/v1/media/compress/jobs", response_model=List[Dict[str, Any]])
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
        job["audio_exists"] = bool(
            job.get("audio_extract_path") and os.path.exists(job.get("audio_extract_path") or "")
        )
    return jobs


@router.get("/v1/media/compress/retention")
async def get_compress_retention_info(
    authenticated: bool = Depends(verify_api_key),
):
    """
    Retention-policy info for the compressor dashboard: how long compressed
    output files are kept on disk (COMPRESS_RETENTION_HOURS) and the timestamp
    + count of the last automatic cleanup that actually removed files.
    """
    return compress_retention_summary()


@router.get("/v1/media/compress/jobs/{job_id}", response_model=CompressJobStatusResponse)
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
    job["audio_exists"] = bool(
        job.get("audio_extract_path") and os.path.exists(job.get("audio_extract_path") or "")
    )
    return CompressJobStatusResponse(**job)


@router.delete("/v1/media/compress/jobs/{job_id}")
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


@router.delete("/v1/media/compress/jobs/{job_id}/output")
async def delete_compress_job_output(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete ONLY the compressed output file(s) (video + extracted audio) of a completed job
    to free disk space, while keeping the job record (history) intact.
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job has no output files.")

    output_path = job.get("output_path")
    audio_path = job.get("audio_extract_path")
    if not output_path and not audio_path:
        raise HTTPException(status_code=400, detail="Job has no output files.")

    base_real = os.path.realpath(COMPRESS_OUTPUT_DIR)
    job_dir_real = os.path.realpath(os.path.join(COMPRESS_OUTPUT_DIR, job_id))

    freed = 0
    removed_any = False

    # 1. Delete compressed video file if it exists
    if output_path:
        out_real = os.path.realpath(output_path)
        if out_real.startswith(base_real + os.sep) and os.path.dirname(out_real) == job_dir_real:
            if os.path.exists(out_real):
                try:
                    freed += os.path.getsize(out_real)
                    os.remove(out_real)
                    removed_any = True
                except OSError as e:
                    logger.error(f"Failed to delete output video file for compress job {job_id}: {e}")

    # 2. Delete extracted audio file if it exists
    if audio_path:
        aud_real = os.path.realpath(audio_path)
        if aud_real.startswith(base_real + os.sep) and os.path.dirname(aud_real) == job_dir_real:
            if os.path.exists(aud_real):
                try:
                    freed += os.path.getsize(aud_real)
                    os.remove(aud_real)
                    removed_any = True
                except OSError as e:
                    logger.error(f"Failed to delete output audio file for compress job {job_id}: {e}")

    if not removed_any:
        return {
            "status": "success",
            "message": "Output files were already removed.",
            "output_size_bytes": job.get("output_size_bytes") or 0,
        }

    logger.info(f"Compress job {job_id}: output file(s) deleted manually (freed {freed} bytes)")
    return {
        "status": "success",
        "message": "Compressed output file(s) deleted. Job record kept for history.",
        "output_size_bytes": freed,
    }


@router.get("/v1/media/compress/jobs/{job_id}/download")
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


@router.get("/v1/media/compress/jobs/{job_id}/audio")
async def download_compress_job_audio(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Download the extracted audio file (WAV or MP3) of a completed compress job.
    Returns 404 if no audio was extracted or the file has been cleaned up.
    """
    job = get_compress_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Compress job {job_id} not found.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet.")
    audio_path = job.get("audio_extract_path")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(
            status_code=404,
            detail="Audio file not found (not extracted or removed by retention policy).",
        )

    base_real = os.path.realpath(COMPRESS_OUTPUT_DIR)
    job_dir_real = os.path.realpath(os.path.join(COMPRESS_OUTPUT_DIR, job_id))
    out_real = os.path.realpath(audio_path)
    if not out_real.startswith(base_real + os.sep) or os.path.dirname(out_real) != job_dir_real:
        raise HTTPException(
            status_code=403, detail="Access to this audio path is not allowed."
        )

    fmt = job.get("audio_extract_format", "wav")
    media_type = "audio/wav" if fmt == "wav" else "audio/mpeg"
    ext = "wav" if fmt == "wav" else "mp3"
    safe_name = os.path.splitext(job.get("filename", "audio"))[0]
    response = FileResponse(out_real, media_type=media_type)
    response.headers["Content-Disposition"] = _attachment_header(safe_name, ext)
    return response


# =========================================================================
