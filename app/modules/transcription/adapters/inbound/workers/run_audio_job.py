"""
Inbound Worker Adapter for Audio Queue Jobs (type='audio').

Reuses the faithful inline transcription logic (run_transcription) — the exact
code path behind the synchronous /v1/audio/transcribe endpoint — and persists
the result into the shared jobs table so the job shows up in the transcription
history page and supports txt/srt/json export.

Result shape stored in result_json:
    { text, segments, elapsed_seconds, duration_seconds, rtf, model }
"""

import sys
import os
import json
import logging

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from app.db import update_job_status
from app.audio_utils import safe_delete_dir
from app.modules.transcription.adapters.inbound.workers.run_inline_transcribe import (
    run_transcription,
    _parse_bool,
    _parse_int,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("choonova-audio-job-worker")


def main():
    if len(sys.argv) < 10:
        logger.error(
            "Usage: python -m app.run_audio_job <job_id> <input_path> <language> "
            "<model> <num_speakers> <min_speakers> <max_speakers> "
            "<enable_diarization> <with_timestamps>"
        )
        sys.exit(1)

    job_id = sys.argv[1]
    input_path = sys.argv[2]
    language = sys.argv[3]
    model = sys.argv[4]
    num_speakers = _parse_int(sys.argv[5])
    min_speakers = _parse_int(sys.argv[6])
    max_speakers = _parse_int(sys.argv[7])
    enable_diarization = _parse_bool(sys.argv[8])
    with_timestamps = _parse_bool(sys.argv[9])

    job_dir = os.path.dirname(input_path)

    logger.info(
        f"🚀 Audio job worker starting: job_id={job_id} lang={language} "
        f"model={model} diar={enable_diarization} ts={with_timestamps}"
    )

    try:
        update_job_status(job_id, status="processing", progress=5.0, stage="transcribing")

        result = run_transcription(
            input_path,
            language,
            with_timestamps,
            model,
            num_speakers,
            min_speakers,
            max_speakers,
            enable_diarization,
        )

        segments = result.get("timestamps") or []
        result_model = result.get("model") or model
        result_json = {
            "text": result.get("text", ""),
            "segments": segments,
            "elapsed_seconds": result.get("elapsed_seconds", 0.0),
            "duration_seconds": result.get("duration_seconds", 0.0),
            "rtf": result.get("rtf", 0.0),
            "model": result_model,
        }

        update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            stage="completed",
            duration=float(result.get("duration_seconds", 0.0)),
            processing_time=float(result.get("elapsed_seconds", 0.0)),
            result_json=json.dumps(result_json, ensure_ascii=False),
            model=result_model,
        )
        logger.info(f"✅ Audio job {job_id} completed (model={result_model})")
    except Exception as e:
        logger.error(f"❌ Audio job {job_id} failed: {e}", exc_info=True)
        try:
            update_job_status(
                job_id,
                status="failed",
                stage="Failed",
                error_json=json.dumps({"message": str(e), "detail": str(e)}, ensure_ascii=False),
            )
        except Exception as e2:
            logger.error(f"Failed to mark audio job {job_id} failed: {e2}")
        sys.exit(1)
    finally:
        try:
            safe_delete_dir(job_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up audio job dir {job_dir}: {e}")


if __name__ == "__main__":
    main()