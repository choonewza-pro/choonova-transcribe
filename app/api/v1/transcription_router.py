
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import time
import uuid
import subprocess
import re
from urllib.parse import quote
import asyncio

from app.core.security import verify_api_key, verify_transcribe_history_api_key
from app.core.state import _active_workers
from app.core.media_validator import validate_magic_bytes, validate_extension, validate_with_ffprobe, secure_filename
from app.config import (
    MAX_AUDIO_UPLOAD_SIZE_MB, MAX_UPLOAD_SIZE_MB,
    TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC, TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC,
    TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC, TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC,
    TRANSCRIBE_MAX_QUEUED,
    TEMP_JOBS_DIR, MIN_FREE_DISK_GB, SERVICE_DIR
)
from app.schemas import TranscribeResponse, JobCreateResponse, JobStatusResponse
from app.modules.transcription.adapters.outbound.repositories.sqlite_job_repository import SQLiteJobRepository
from app.modules.transcription.adapters.outbound.media.ffmpeg_audio_adapter import FFmpegAudioAdapter
from app.modules.transcription.adapters.outbound.engines.engine_router import EngineRouterAdapter
from app.modules.transcription.application.transcription_service import TranscriptionService
import logging

logger = logging.getLogger("typhoon-asr-transcription")

router = APIRouter(tags=["Transcription"])


def get_transcription_service() -> TranscriptionService:
    repo = SQLiteJobRepository()
    engine = EngineRouterAdapter()
    media = FFmpegAudioAdapter()
    return TranscriptionService(repo, engine, media)


def dir_has_files(dir_path: str) -> bool:
    try:
        if os.path.isdir(dir_path):
            with os.scandir(dir_path) as it:
                return any(it)
    except Exception:
        pass
    return False


def _job_to_dict(job) -> Dict[str, Any]:
    """Convert TranscriptionJob entity to a plain dict for JSON responses."""
    from datetime import datetime
    now_iso = datetime.utcnow().isoformat()
    return {
        "id": job.id,
        "type": getattr(job, "type", None) or "transcription",
        "filename": job.filename,
        "file_size_bytes": job.file_size_bytes or 0,
        "language": job.language or "th",
        "status": job.status,
        "progress": job.progress or 0.0,
        "stage": job.stage or "queued",
        "total_chunks": job.total_chunks or 0,
        "completed_chunks": job.completed_chunks or 0,
        "duration": job.duration or 0.0,
        "processing_time": job.processing_time or 0.0,
        "target_chunk_sec": getattr(job, "target_chunk_sec", None) or 30.0,
        "max_chunk_sec": getattr(job, "max_chunk_sec", None) or 60.0,
        "enable_diarization": getattr(job, "enable_diarization", False),
        "num_speakers": getattr(job, "num_speakers", None),
        "min_speakers": getattr(job, "min_speakers", None),
        "max_speakers": getattr(job, "max_speakers", None),
        "task": getattr(job, "task", None) or "transcribe",
        "model": job.model,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at or now_iso,
        "updated_at": job.updated_at or now_iso,
        "started_at": getattr(job, "started_at", None),
        "completed_at": getattr(job, "completed_at", None),
    }


@router.post("/v1/audio/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    with_timestamps: bool = Form(False),
    language: str = Form("th"),
    task: str = Form("transcribe"),
    enable_diarization: bool = Form(False),
    num_speakers: Optional[int] = Form(None),
    min_speakers: Optional[int] = Form(None),
    max_speakers: Optional[int] = Form(None),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Transcribe or translate an uploaded audio file (WAV, MP3, M4A, OGG, FLAC).

    language: 'th' (default, Typhoon Thai ASR), 'en' (Whisper English), or
    'auto' (Whisper auto-detect for Thai/English mixed audio).
    task: 'transcribe' (default) or 'translate' (translate to English via Whisper).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio file must be provided.")

    validate_extension(file.filename)

    lang_clean = (language or "th").strip().lower()
    if lang_clean in ("translate_en", "translate"):
        task = "translate"
        lang = "auto"
    elif task == "translate":
        lang = "auto" if lang_clean not in ("th", "en") else lang_clean
    else:
        try:
            lang = TranscriptionService.normalize_language(language)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if num_speakers is not None and num_speakers <= 0:
        raise HTTPException(status_code=422, detail="num_speakers must be greater than 0.")
    if min_speakers is not None and min_speakers <= 0:
        raise HTTPException(status_code=422, detail="min_speakers must be greater than 0.")
    if max_speakers is not None and max_speakers <= 0:
        raise HTTPException(status_code=422, detail="max_speakers must be greater than 0.")
    if min_speakers is not None and max_speakers is not None and min_speakers > max_speakers:
        raise HTTPException(status_code=422, detail="min_speakers cannot exceed max_speakers.")

    if num_speakers or min_speakers or max_speakers:
        enable_diarization = True

    svc = get_transcription_service()

    if not svc.check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free disk space is required.",
        )

    try:
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

        start_t = time.time()
        temp_audio_path = None

        if enable_diarization:
            # Diarization requires writing audio to a temporary file
            temp_dir = os.path.join(TEMP_JOBS_DIR, f"sync_{uuid.uuid4()}")
            os.makedirs(temp_dir, exist_ok=True)
            safe_name = secure_filename(file.filename)
            ext = os.path.splitext(safe_name)[1] or ".wav"
            temp_audio_path = os.path.join(temp_dir, f"input{ext}")

            with open(temp_audio_path, "wb") as f:
                f.write(content)

            # Convert to 16kHz mono WAV before diarization. PyAnnote's Audio.crop()
            # re-decodes the file per segmentation chunk; feeding it the raw MP3/FLAC/OGG
            # costs seconds per crop (~3500x slower than WAV), turning a 1-minute job
            # into a 10+ minute grind. The media/worker path already converts first.
            from app.audio_utils import extract_audio_ffmpeg
            temp_wav_path = os.path.join(temp_dir, "diarization_input.wav")
            await asyncio.to_thread(extract_audio_ffmpeg, temp_audio_path, temp_wav_path)

            if task == "translate":
                from app.engine_router import transcribe_file as router_transcribe_file
                from app.pyannote_engine import (
                    diarize_audio,
                    merge_speaker_overlap,
                    group_speaker_segments,
                )

                res = await asyncio.to_thread(
                    router_transcribe_file,
                    audio_path=temp_audio_path,
                    language=lang,
                    with_timestamps=True,
                    task="translate",
                )
                text = res.get("text", "")
                timestamps = res.get("timestamps", [])
                turns = await asyncio.to_thread(
                    diarize_audio,
                    temp_wav_path,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                timestamps = merge_speaker_overlap(timestamps, turns)
                grouped = group_speaker_segments(timestamps)
                if grouped:
                    text = "\n".join(
                        f"[{s['speaker']}]: {s['text']}" for s in grouped
                    )
            elif lang == "th":
                from app.engine_router import transcribe_file as router_transcribe_file
                from app.pyannote_engine import (
                    diarize_audio,
                    merge_speaker_overlap,
                    group_speaker_segments,
                )

                res = await asyncio.to_thread(
                    router_transcribe_file,
                    audio_path=temp_audio_path,
                    language=lang,
                    with_timestamps=True,
                )
                text = res.get("text", "")
                timestamps = res.get("timestamps", [])
                turns = await asyncio.to_thread(
                    diarize_audio,
                    temp_wav_path,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                timestamps = merge_speaker_overlap(timestamps, turns)
                grouped = group_speaker_segments(timestamps)
                if grouped:
                    text = "\n".join(
                        f"[{s['speaker']}]: {s['text']}" for s in grouped
                    )
            else:
                from app.whisperx_engine import transcribe_and_diarize_whisperx
                wx_res = await asyncio.to_thread(
                    transcribe_and_diarize_whisperx,
                    temp_wav_path,
                    lang,
                    num_speakers,
                    min_speakers,
                    max_speakers,
                )
                text = wx_res.get("text", "")
                timestamps = wx_res.get("segments", [])

            elapsed = time.time() - start_t
            from app.audio_utils import get_audio_duration_ffmpeg
            duration = get_audio_duration_ffmpeg(temp_audio_path)
            svc.safe_delete_dir(temp_dir)
        else:
            # Inline transcription via engine port
            from app.engine_router import transcribe_bytes as router_transcribe_bytes
            res = await asyncio.to_thread(
                router_transcribe_bytes,
                audio_bytes=content,
                filename_hint=secure_filename(file.filename),
                language=lang,
                with_timestamps=with_timestamps,
                task=task,
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
            timestamps=timestamps if (with_timestamps or enable_diarization) else None,
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
    task: str = Form("transcribe"),
    target_chunk_sec: float = Form(None),
    max_chunk_sec: float = Form(None),
    enable_diarization: bool = Form(False),
    num_speakers: Optional[int] = Form(None),
    min_speakers: Optional[int] = Form(None),
    max_speakers: Optional[int] = Form(None),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Upload a large video/audio file (MP4, MKV, MOV, WAV up to 1GB+) for long-form transcription.
    Returns job_id immediately with 202 Accepted status for async background processing.

    language: 'th' (default, Typhoon Thai ASR), 'en' (Whisper English),
    'auto' (Whisper auto-detect for Thai/English mixed audio), or 'translate_en' (Whisper speech-to-English translation).

    target_chunk_sec / max_chunk_sec: chunk duration bounds for silence-based splitting.
    Defaults come from env based on the selected language model.
    """
    if not file.filename:
        raise HTTPException(
            status_code=400, detail="Video/Audio file must be provided."
        )

    validate_extension(file.filename)

    lang_clean = (language or "th").strip().lower()
    task_clean = (task or "transcribe").strip().lower()
    if lang_clean in ("translate_en", "translate") or task_clean == "translate":
        task_mode = "translate"
        lang = "auto"
    else:
        task_mode = "transcribe"
        try:
            lang = TranscriptionService.normalize_language(language)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if num_speakers is not None and num_speakers <= 0:
        raise HTTPException(status_code=422, detail="num_speakers must be greater than 0.")
    if min_speakers is not None and min_speakers <= 0:
        raise HTTPException(status_code=422, detail="min_speakers must be greater than 0.")
    if max_speakers is not None and max_speakers <= 0:
        raise HTTPException(status_code=422, detail="max_speakers must be greater than 0.")
    if min_speakers is not None and max_speakers is not None and min_speakers > max_speakers:
        raise HTTPException(status_code=422, detail="min_speakers cannot exceed max_speakers.")

    if num_speakers or min_speakers or max_speakers:
        enable_diarization = True

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

    svc = get_transcription_service()

    queued = svc.count_queued()
    if queued >= TRANSCRIBE_MAX_QUEUED:
        raise HTTPException(
            status_code=429,
            detail=f"Transcription queue is full ({TRANSCRIBE_MAX_QUEUED} jobs). "
            "Wait for pending jobs to finish and try again.",
        )

    if not svc.check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
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
        svc.safe_delete_dir(job_dir)
        raise
    except Exception as e:
        svc.safe_delete_dir(job_dir)
        logger.error(f"Error saving upload file for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save upload file: {e}")

    try:
        with open(save_path, "rb") as f:
            header_bytes = f.read(2048)
        validate_magic_bytes(header_bytes)
        validate_with_ffprobe(save_path)
    except HTTPException:
        svc.safe_delete_dir(job_dir)
        raise
    except Exception as e:
        svc.safe_delete_dir(job_dir)
        logger.error(f"Validation error for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate media file")

    # Create job record via service → repository port (queued status)
    job = svc.create_job(
        job_id=job_id,
        filename=file.filename,
        file_size_bytes=total_bytes,
        language=lang,
        target_chunk_sec=target_chunk_sec,
        max_chunk_sec=max_chunk_sec,
        enable_diarization=enable_diarization,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        task=task_mode,
    )

    return JobCreateResponse(
        status="accepted",
        id=job.id,
        filename=file.filename,
        language=lang,
        task=task_mode,
        enable_diarization=enable_diarization,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        message="Job created and enqueued for long-form video transcription",
    )


@router.get("/v1/media/transcribe/jobs", response_model=List[Dict[str, Any]])
async def list_transcription_jobs(
    limit: int = 50,
    status_filter: Optional[str] = None,
    include_text: bool = False,
    authenticated: bool = Depends(verify_transcribe_history_api_key),
):
    """
    List recent transcription jobs ordered by creation date.
    By default excludes heavy text columns (result_text/srt_text/timestamps_json).
    Each row includes 'media_files_exist' indicating whether the media files are still on disk.
    """
    svc = get_transcription_service()
    jobs = svc.list_jobs(limit=limit, status_filter=status_filter)
    result = []
    for job in jobs:
        d = _job_to_dict(job)
        d["media_files_exist"] = dir_has_files(os.path.join(TEMP_JOBS_DIR, job.id))
        if not include_text:
            d.pop("result", None)
        result.append(d)
    return result


@router.get("/v1/media/transcribe/jobs/{job_id}", response_model=JobStatusResponse)
async def get_transcription_job_status(
    job_id: str, authenticated: bool = Depends(verify_transcribe_history_api_key)
):
    """
    Get the status, stage, progress %, and completed transcript result of a job.
    """
    svc = get_transcription_service()
    job = svc.get_job_or_none(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return JobStatusResponse(**_job_to_dict(job))


@router.delete("/v1/media/transcribe/jobs/{job_id}")
async def cancel_transcription_job(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Cancel a running transcription job, or delete a terminal job.
    """
    svc = get_transcription_service()
    job = svc.get_job_or_none(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    proc = _active_workers.pop(job_id, None)
    if proc is not None and proc.poll() is None:
        logger.info(f"Terminating worker subprocess for job {job_id} (cancel request)")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            logger.warning(f"Worker {job_id} did not exit after terminate; killing it")
            proc.kill()

    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)

    if job.status in ["queued", "processing"]:
        svc.update_status(job_id=job_id, status="cancelled")
        svc.safe_delete_dir(job_dir)
        return {"status": "success", "message": f"Job {job_id} cancelled."}
    else:
        svc.delete_job(job_id)
        svc.safe_delete_dir(job_dir)
        return {"status": "success", "message": f"Job {job_id} deleted."}


@router.delete("/v1/media/transcribe/jobs/{job_id}/media")
async def delete_transcription_job_media(
    job_id: str, authenticated: bool = Depends(verify_api_key)
):
    """
    Delete only the on-disk media files of a job (free machine resources)
    while KEEPING the transcription record (text/SRT/timestamps) in SQLite.
    """
    svc = get_transcription_service()
    job = svc.get_job_or_none(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    job_dir = os.path.join(TEMP_JOBS_DIR, job_id)
    if not dir_has_files(job_dir):
        return {
            "status": "success",
            "media_deleted": False,
            "message": "No media files found for this job (transcription record kept).",
        }

    svc.safe_delete_dir(job_dir)
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
    job_id: str, export_format: str, authenticated: bool = Depends(verify_transcribe_history_api_key)
):
    """
    Download job transcription result as .txt, .srt subtitles, or .json timestamp format.
    """
    svc = get_transcription_service()
    job = svc.get_job_or_none(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet.")

    export_format = export_format.lower()
    safe_name = os.path.splitext(job.filename or "transcript")[0]
    result = job.result or {}

    if export_format == "txt":
        content = result.get("text", "")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(safe_name, "txt")},
        )
    elif export_format == "srt":
        segments = result.get("segments", [])
        content = TranscriptionService.build_srt_subtitles(segments)
        return Response(
            content=content,
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(safe_name, "srt")},
        )
    elif export_format == "json":
        data = {
            "id": job.id,
            "filename": job.filename,
            "duration": job.duration,
            "text": result.get("text"),
            "segments": result.get("segments"),
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
