import sys
import os
import asyncio
import logging

# Ensure parent directory is in sys.path for app module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.job_worker import process_transcription_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("typhoon-asr-worker-cli")


def main():
    if len(sys.argv) < 3:
        logger.error("Usage: python -m app.run_job <job_id> <input_file_path>")
        sys.exit(1)

    job_id = sys.argv[1]
    input_file_path = sys.argv[2]

    logger.info(f"🚀 Isolated Worker process starting for job_id={job_id}")

    try:
        asyncio.run(process_transcription_job(job_id, input_file_path))
        logger.info(f"✅ Isolated Worker finished processing for job_id={job_id}")
    except Exception as e:
        logger.error(f"❌ Isolated Worker failed for job_id={job_id}: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
