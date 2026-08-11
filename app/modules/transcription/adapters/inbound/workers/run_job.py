"""
Inbound Worker Adapter for Long-form Transcription Subprocess execution.
"""

import sys
import os
import asyncio
import logging

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from app.job_worker import process_transcription_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("choonova-transcription-worker")


def main():
    if len(sys.argv) < 3:
        logger.error("Usage: python -m app.modules.transcription.adapters.inbound.workers.run_job <job_id> <input_file_path> [language]")
        sys.exit(1)

    job_id = sys.argv[1]
    input_file_path = sys.argv[2]
    language = sys.argv[3] if len(sys.argv) > 3 else "th"

    logger.info(f"🚀 Transcription Inbound Worker starting for job_id={job_id}")

    try:
        asyncio.run(process_transcription_job(job_id, input_file_path, language))
        logger.info(f"✅ Transcription Inbound Worker finished for job_id={job_id}")
    except Exception as e:
        logger.error(f"❌ Transcription Inbound Worker failed for job_id={job_id}: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
