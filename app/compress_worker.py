import os
import time
import asyncio
import logging
from typing import List, Optional

from app.db import get_compress_job, update_compress_job
from app.compress_utils import (
    probe_video,
    build_compress_cmd,
    parse_progress_line,
    normalize_encoder,
    normalize_preset,
)
from app.audio_utils import safe_delete_file, safe_delete_dir

logger = logging.getLogger("typhoon-asr-compress-worker")

# Throttle DB progress writes: at most once per second per job to keep SQLite
# writes cheap for long encodes.
PROGRESS_UPDATE_INTERVAL_SEC = 1.0


async def _read_stderr_tail(stream, lines: int = 40) -> str:
    """Consume stderr to avoid pipe deadlock; keep the last `lines` lines."""
    tail: List[str] = []
    try:
        async for raw in stream:
            tail.append(raw.decode("utf-8", errors="replace"))
            if len(tail) > lines * 2:
                tail = tail[-lines:]
    except Exception:
        pass
    return "".join(tail[-lines:])


def _maybe_write_terminal(job_id: str, status: str, **kwargs) -> bool:
    """
    Write a terminal state (completed/failed) ONLY if the job row still exists
    and is still 'processing'. This guards against:
      - server restart recovery already flipping the row to 'failed'
      - user cancellation (DELETE) removing the row mid-encode
      - an orphaned worker overwriting the recovered state after a restart
    """
    job = get_compress_job(job_id)
    if not job:
        return False
    if job.get("status") != "processing":
        return False
    update_compress_job(job_id, status=status, **kwargs)
    return True


async def process_compress_job(
    job_id: str,
    input_file_path: str,
    target_width: int = 0,
    bitrate_kbps: int = 0,
    crf: int = 28,
    preset: str = "medium",
    encoder: str = "libx264",
) -> None:
    """
    Async background worker that compresses a video with FFmpeg and updates the
    job's progress in SQLite. The input file is ALWAYS deleted on completion,
    failure, or cancellation (handled by the caller), plus a defensive cleanup
    in the finally block below.
    """
    start_time = time.time()
    job_dir = os.path.dirname(input_file_path)
    encoder = normalize_encoder(encoder)
    preset = normalize_preset(preset, encoder)
    output_path = os.path.join(job_dir, "compressed.mp4")

    completed_ok = False

    try:
        # ---- Step 1: probe source ----
        update_compress_job(
            job_id, status="processing", progress_pct=1.0,
            current_stage="Probing video (ffprobe)",
        )
        probe = probe_video(input_file_path)
        if probe.get("duration_seconds", 0) > 0:
            update_compress_job(job_id, duration_seconds=probe["duration_seconds"])
        if probe.get("width", 0) > 0:
            update_compress_job(
                job_id, input_width=probe["width"], input_height=probe["height"]
            )
        logger.info(
            f"Compress {job_id}: probe result {probe.get('width')}x"
            f"{probe.get('height')}, duration={probe.get('duration_seconds'):.2f}s, "
            f"has_audio={probe.get('has_audio')}, encoder={encoder}, preset={preset}"
        )

        # ---- Step 2: build + run FFmpeg ----
        update_compress_job(
            job_id, status="processing", progress_pct=2.0,
            current_stage="Starting FFmpeg encode",
        )
        cmd = build_compress_cmd(
            input_path=input_file_path,
            output_path=output_path,
            target_width=target_width,
            bitrate_kbps=bitrate_kbps,
            crf=crf,
            preset=preset,
            encoder=encoder,
            probe=probe,
        )
        logger.info(f"FFmpeg command: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.ensure_future(_read_stderr_tail(proc.stderr))

        duration = probe.get("duration_seconds", 0.0) or 0.0
        last_progress_write = 0.0
        last_pct = 2.0

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            out_sec, is_end = parse_progress_line(line)
            if is_end:
                break
            if out_sec is None or duration <= 0:
                continue
            pct = min(99.0, 2.0 + (out_sec / duration) * 97.0)
            now = time.time()
            if pct - last_pct >= 1.0 or now - last_progress_write >= PROGRESS_UPDATE_INTERVAL_SEC:
                last_pct = pct
                last_progress_write = now
                update_compress_job(
                    job_id, progress_pct=pct,
                    current_stage=f"Compressing ({pct:.0f}%)",
                )

        returncode = await proc.wait()
        stderr_tail = await stderr_task
        if returncode != 0:
            raise RuntimeError(
                f"FFmpeg exited with code {returncode}:\n{stderr_tail.strip()[-1000:]}"
            )

        # ---- Step 3: verify output + record result ----
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("FFmpeg finished but produced an empty/missing output file")

        output_size = os.path.getsize(output_path)
        out_probe = probe_video(output_path)
        elapsed = time.time() - start_time

        completed_ok = _maybe_write_terminal(
            job_id,
            status="completed",
            progress_pct=100.0,
            current_stage="Completed",
            output_path=output_path,
            output_size_bytes=output_size,
            output_width=out_probe.get("width", 0),
            output_height=out_probe.get("height", 0),
            elapsed_seconds=elapsed,
        )
        logger.info(
            f"Compress {job_id} completed in {elapsed:.2f}s "
            f"({output_size} bytes -> {output_path})"
        )

    except Exception as e:
        logger.error(f"Compress {job_id} failed: {e}", exc_info=True)
        # Remove the partial output file so a failed job does not leak disk.
        safe_delete_file(output_path)
        _maybe_write_terminal(
            job_id, status="failed", current_stage="Failed", error_message=str(e)
        )

    finally:
        # Defensive cleanup: the input MUST always be deleted (it can be huge).
        # The compressed output is kept ONLY when the job completed and was
        # recorded; otherwise it is removed too.
        safe_delete_file(input_file_path)
        if not completed_ok:
            safe_delete_file(output_path)
        try:
            for name in os.listdir(job_dir):
                if name != os.path.basename(output_path):
                    safe_delete_file(os.path.join(job_dir, name))
        except OSError:
            pass
