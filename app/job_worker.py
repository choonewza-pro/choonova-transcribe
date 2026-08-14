import os
import json
import time
import asyncio
import logging
from typing import List, Dict, Any
from datetime import timedelta

from app.config import (
    TEMP_JOBS_DIR,
    TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC,
    TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC,
    TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC,
    TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC,
)
from app.db import update_job_status, get_job
from app.audio_utils import (
    extract_audio_ffmpeg,
    split_audio_silence,
    safe_delete_file,
    safe_delete_dir,
    get_audio_duration_ffmpeg,
)
from app.cuda_utils import is_cuda_error, is_allocator_corruption
from app.asr_engine import engine
from app.whisper_engine import whisper_engine
from app.engine_router import (
    transcribe_file as router_transcribe_file,
    reset_all,
    cuda_device_reset_all,
)

logger = logging.getLogger("typhoon-asr-job-worker")

# Global PyTorch GPU VRAM Concurrency Lock
gpu_lock = asyncio.Lock()

# Transient CUDA driver errors (e.g. "CUDA driver error: device not ready")
# can hit long-running jobs after many consecutive transcribe calls. Retry with
# backoff + CUDA context recovery so a single driver hiccup doesn't discard the job.
CUDA_RETRY_ATTEMPTS = int(os.getenv("CUDA_RETRY_ATTEMPTS", "3"))
CUDA_RETRY_BACKOFF_SEC = float(os.getenv("CUDA_RETRY_BACKOFF_SEC", "5"))
CUDA_RESET_ON_ALLOCATOR_ERROR = os.getenv(
    "CUDA_RESET_ON_ALLOCATOR_ERROR", "false"
).lower() in (
    "1",
    "true",
    "yes",
)
# Reset the CUDA context (cudaDeviceReset + model reload) after each chunk to
# prevent CUDACachingAllocator corruption that accumulates across consecutive
# model.transcribe() calls. The canonical symptom is "CUDA error: an illegal
# memory access was encountered" terminating the worker on chunk 2/2. Costs
# ~6s of model reload per chunk but eliminates the crash class entirely.
CUDA_RESET_BETWEEN_CHUNKS = os.getenv("CUDA_RESET_BETWEEN_CHUNKS", "true").lower() in (
    "1",
    "true",
    "yes",
)


async def transcribe_chunk_with_retry(
    loop: asyncio.AbstractEventLoop,
    chunk_path: str,
    with_timestamps: bool,
    chunk_idx: int,
    language: str = "th",
) -> Dict[str, Any]:
    """
    Run the routed engine's transcribe_file for a single chunk, retrying on
    transient CUDA errors with exponential backoff.

    Two-tier recovery:
    - Tier 1 (transient driver error): backoff + clear_cuda_cache() + retry.
    - Tier 2 (allocator corruption): backoff retries are useless; do a full
      CUDA device reset (cudaDeviceReset), reload all models, and retry once.
    """
    for attempt in range(1, CUDA_RETRY_ATTEMPTS + 1):
        try:
            return await loop.run_in_executor(
                None,
                router_transcribe_file,
                chunk_path,
                language,
                with_timestamps,
                True,
            )
        except Exception as e:
            if not is_cuda_error(e):
                raise
            if is_allocator_corruption(e) and CUDA_RESET_ON_ALLOCATOR_ERROR:
                # Allocator corruption: skip incremental retries, nuke context.
                logger.warning(
                    f"Chunk {chunk_idx} hit CUDA allocator corruption: {e}. "
                    f"Performing full CUDA device reset + model reload before one final retry."
                )
                await loop.run_in_executor(None, cuda_device_reset_all)
                return await loop.run_in_executor(
                    None,
                    router_transcribe_file,
                    chunk_path,
                    language,
                    with_timestamps,
                    True,
                )
            if is_allocator_corruption(e):
                # Allocator corruption but device reset disabled: keep reloading
                # the model so the next chunk starts from a fresh context.
                logger.warning(
                    f"Chunk {chunk_idx} hit CUDA allocator corruption: {e}. "
                    f"Reloading model and retrying once more (device reset disabled)."
                )
                await loop.run_in_executor(None, reset_all)
                return await loop.run_in_executor(
                    None,
                    router_transcribe_file,
                    chunk_path,
                    language,
                    with_timestamps,
                    True,
                )
            if attempt == CUDA_RETRY_ATTEMPTS:
                logger.warning(
                    f"Chunk {chunk_idx} failed {attempt} attempts with CUDA error: {e}; "
                    f"reloading model and retrying once more"
                )
                await loop.run_in_executor(None, reset_all)
                return await loop.run_in_executor(
                    None,
                    router_transcribe_file,
                    chunk_path,
                    language,
                    with_timestamps,
                    True,
                )
            backoff = CUDA_RETRY_BACKOFF_SEC * attempt
            logger.warning(
                f"Chunk {chunk_idx} CUDA error (attempt {attempt}/{CUDA_RETRY_ATTEMPTS}): {e}; "
                f"retrying in {backoff:.0f}s"
            )
            await loop.run_in_executor(None, engine.clear_cuda_cache)
            await asyncio.sleep(backoff)

    raise RuntimeError(
        "Unreachable: transcribe_chunk_with_retry exhausted all attempts"
    )


def format_timestamp_srt(seconds: float) -> str:
    """
    Format seconds (e.g. 12.345) to SRT timestamp string: 00:00:12,345
    """
    if seconds < 0:
        seconds = 0.0
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt_subtitles(
    timestamps: List[Dict[str, Any]],
    max_words_per_cue: int = 8,
    max_gap_sec: float = 1.0,
) -> str:
    """
    Group continuous word/segment timestamps into SRT subtitle cues.
    Supports both word-level timestamps and speaker-grouped segments.
    """
    if not timestamps:
        return ""

    cues = []
    current_cue_words = []
    current_cue_start = None
    current_cue_speaker = None
    last_word_end = 0.0

    for item in timestamps:
        word = (item.get("word") or item.get("text") or "").strip()
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        speaker = item.get("speaker")

        if not word:
            continue

        if current_cue_start is None:
            current_cue_start = start
            current_cue_speaker = speaker

        # Check if we should finalize current cue
        is_long_gap = (
            (start - last_word_end) > max_gap_sec if last_word_end > 0 else False
        )
        is_max_words = len(current_cue_words) >= max_words_per_cue
        is_speaker_change = (
            speaker != current_cue_speaker if current_cue_speaker is not None and speaker is not None else False
        )

        if current_cue_words and (is_long_gap or is_max_words or is_speaker_change):
            cue_text = " ".join(current_cue_words)
            if current_cue_speaker and not cue_text.startswith("["):
                cue_text = f"[{current_cue_speaker}]: {cue_text}"
            cues.append(
                {
                    "start": current_cue_start,
                    "end": last_word_end,
                    "text": cue_text,
                }
            )
            current_cue_words = [word]
            current_cue_start = start
            current_cue_speaker = speaker
        else:
            current_cue_words.append(word)

        last_word_end = end

    if current_cue_words and current_cue_start is not None:
        cue_text = " ".join(current_cue_words)
        if current_cue_speaker and not cue_text.startswith("["):
            cue_text = f"[{current_cue_speaker}]: {cue_text}"
        cues.append(
            {
                "start": current_cue_start,
                "end": last_word_end,
                "text": cue_text,
            }
        )

    # Render SRT string
    srt_lines = []
    for idx, cue in enumerate(cues, 1):
        start_str = format_timestamp_srt(cue["start"])
        end_str = format_timestamp_srt(cue["end"])
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{cue['text']}\n")

    return "\n".join(srt_lines)


async def process_transcription_job(
    job_id: str, input_file_path: str, language: str = "th", enable_diarization: bool = False
) -> None:
    """
    Asynchronous Background Worker for processing long video/audio transcription jobs.
    Handles 4 Pathways:
      - Path 1: Thai without diarization (Typhoon ASR)
      - Path 2: Eng/Auto without diarization (Faster-Whisper)
      - Path 3: Thai with diarization (Typhoon ASR + PyAnnote 3.1)
      - Path 4: Eng/Auto with diarization (WhisperX pipeline)
    """
    logger.info(f"Starting job worker for job_id={job_id} ({input_file_path}, lang={language}, diarization={enable_diarization})")
    start_time = time.time()
    job_dir = os.path.dirname(input_file_path)

    try:
        # Step 1: Extract Audio (MP4 -> 16kHz WAV)
        update_job_status(
            id=job_id,
            status="processing",
            progress=10.0,
            stage="extracting_audio",
        )

        job = get_job(job_id)
        if job and job.get("enable_diarization"):
            enable_diarization = True

        extracted_wav = os.path.join(job_dir, "extracted_audio.wav")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, extract_audio_ffmpeg, input_file_path, extracted_wav
        )

        total_duration = get_audio_duration_ffmpeg(extracted_wav)
        update_job_status(id=job_id, duration=total_duration)

        result_obj = {}

        # -----------------------------------------------------------------
        # Path 4: Eng/Auto + Speaker Diarization -> WhisperX Pipeline
        # -----------------------------------------------------------------
        if enable_diarization and language != "th":
            async with gpu_lock:
                logger.info(f"Acquired GPU Lock for job {job_id} (WhisperX Diarization Pipeline)")
                update_job_status(
                    id=job_id,
                    status="processing",
                    progress=30.0,
                    stage="transcribing",
                )
                from app.whisperx_engine import transcribe_and_diarize_whisperx

                wx_res = await loop.run_in_executor(
                    None, transcribe_and_diarize_whisperx, extracted_wav, language
                )
                result_obj = {
                    "text": wx_res.get("text", ""),
                    "segments": wx_res.get("segments", []),
                }

        # -----------------------------------------------------------------
        # Path 1, 2, 3: Standard Chunking (Typhoon / Faster-Whisper)
        # -----------------------------------------------------------------
        else:
            # Step 2: Silence-Aware Audio Chunking
            update_job_status(
                id=job_id, status="processing", progress=20.0, stage="chunking"
            )
            fallback_target = (
                TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC if language == "th"
                else TRANSCRIBE_WHISPER_TARGET_CHUNK_DURATION_SEC
            )
            fallback_max = (
                TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC if language == "th"
                else TRANSCRIBE_WHISPER_MAX_CHUNK_DURATION_SEC
            )

            target_chunk_sec = (
                job.get("target_chunk_sec") if job and job.get("target_chunk_sec") else fallback_target
            )
            max_chunk_sec = (
                job.get("max_chunk_sec") if job and job.get("max_chunk_sec") else fallback_max
            )

            chunks_dir = os.path.join(job_dir, "chunks")
            chunks = await loop.run_in_executor(
                None,
                split_audio_silence,
                extracted_wav,
                chunks_dir,
                target_chunk_sec,
                max_chunk_sec,
            )

            total_chunks = len(chunks)
            update_job_status(id=job_id, total_chunks=total_chunks, progress=25.0)

            combined_text_parts = []
            global_timestamps = []

            # Step 3: GPU Transcription Loop (Protected by asyncio.Lock)
            async with gpu_lock:
                logger.info(
                    f"Acquired GPU Lock for job {job_id} (Processing {total_chunks} chunks)"
                )

                update_job_status(
                    id=job_id,
                    status="processing",
                    progress=25.0,
                    stage="transcribing",
                )
                if language == "th":
                    await loop.run_in_executor(None, engine.load_model)
                else:
                    await loop.run_in_executor(None, whisper_engine.load_model)

                for idx, chunk in enumerate(chunks, 1):
                    pct_max = 85.0 if enable_diarization else 95.0
                    pct = 25.0 + (idx / total_chunks) * (pct_max - 25.0)
                    update_job_status(
                        id=job_id,
                        status="processing",
                        progress=pct,
                        completed_chunks=idx - 1,
                        stage="transcribing",
                    )

                    chunk_path = chunk["path"]
                    chunk_start_sec = chunk["start_sec"]
                    chunk_duration = chunk.get("duration_sec", 0.0)
                    logger.info(
                        f"Transcribing chunk {idx}/{total_chunks} "
                        f"(start={chunk_start_sec:.1f}s, duration={chunk_duration:.1f}s)"
                    )

                    res = await transcribe_chunk_with_retry(
                        loop, chunk_path, True, idx, language
                    )

                    chunk_text = res.get("text", "").strip()
                    if chunk_text:
                        combined_text_parts.append(chunk_text)

                    chunk_ts = res.get("timestamps", [])
                    for ts_item in chunk_ts:
                        word = ts_item.get("word", "")
                        w_start = float(ts_item.get("start", 0.0)) + chunk_start_sec
                        w_end = float(ts_item.get("end", 0.0)) + chunk_start_sec
                        global_timestamps.append(
                            {
                                "word": word,
                                "start": round(w_start, 3),
                                "end": round(w_end, 3),
                            }
                        )

                    safe_delete_file(chunk_path)
                    engine.clear_cuda_cache()
                    update_job_status(id=job_id, completed_chunks=idx)

                    if CUDA_RESET_BETWEEN_CHUNKS and idx < total_chunks:
                        await loop.run_in_executor(None, cuda_device_reset_all)

                # Path 3: Thai + Diarization (PyAnnote 3.1)
                if enable_diarization and language == "th":
                    logger.info(f"Running Path 3: PyAnnote Diarization for Thai job {job_id}")
                    update_job_status(
                        id=job_id,
                        status="processing",
                        progress=88.0,
                        stage="diarizing",
                    )

                    # Reset ASR model to clear VRAM before loading PyAnnote
                    await loop.run_in_executor(None, reset_all)

                    from app.pyannote_engine import (
                        diarize_audio,
                        merge_speaker_overlap,
                        group_speaker_segments,
                    )

                    turns = await loop.run_in_executor(None, diarize_audio, extracted_wav)
                    merged_timestamps = merge_speaker_overlap(global_timestamps, turns)
                    grouped_segments = group_speaker_segments(merged_timestamps)

                    full_text = "\n".join(
                        [f"[{s['speaker']}]: {s['text']}" for s in grouped_segments]
                    ) if grouped_segments else " ".join(combined_text_parts)

                    result_obj = {
                        "text": full_text,
                        "segments": grouped_segments,
                    }
                else:
                    full_text = " ".join(combined_text_parts)
                    segments = [
                        {"text": ts["word"], "start": ts["start"], "end": ts["end"]}
                        for ts in global_timestamps
                    ]
                    result_obj = {
                        "text": full_text,
                        "segments": segments,
                    }

            safe_delete_dir(chunks_dir)

        # Step 4: Final Cleanup & DB Result Update
        safe_delete_file(extracted_wav)
        safe_delete_file(input_file_path)
        safe_delete_dir(job_dir)

        elapsed = time.time() - start_time

        update_job_status(
            id=job_id,
            status="completed",
            progress=100.0,
            stage="completed",
            result_json=json.dumps(result_obj),
            processing_time=elapsed,
        )
        logger.info(
            f"Job {job_id} completed successfully in {elapsed:.2f}s (Duration: {total_duration:.2f}s)"
        )

    except Exception as e:
        logger.error(f"Job {job_id} failed with error: {e}", exc_info=True)
        safe_delete_dir(job_dir)
        error_obj = {
            "code": "INTERNAL_ERROR",
            "message": str(e),
            "retryable": False
        }
        update_job_status(
            id=job_id, status="failed", stage="completed", error_json=json.dumps(error_obj)
        )

