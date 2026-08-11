import sys
import os
import asyncio
import logging

# Ensure parent directory is in sys.path for app module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.compress_worker import process_compress_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("typhoon-asr-compress-cli")


def main():
    if len(sys.argv) < 3:
        logger.error(
            "Usage: python -m app.run_compress_job <job_id> <input_file_path> "
            "[target_width] [bitrate_kbps] [crf] [preset] [encoder] "
            "[trim_start] [trim_end]"
        )
        sys.exit(1)

    job_id = sys.argv[1]
    input_file_path = sys.argv[2]

    def _int_arg(idx: int, default: int) -> int:
        try:
            return int(sys.argv[idx]) if len(sys.argv) > idx else default
        except ValueError:
            return default

    def _float_arg(idx: int, default: float) -> float:
        try:
            return float(sys.argv[idx]) if len(sys.argv) > idx else default
        except ValueError:
            return default

    target_width = _int_arg(3, 0)
    bitrate_kbps = _int_arg(4, 0)
    crf = _int_arg(5, 28)
    preset = sys.argv[6] if len(sys.argv) > 6 else "medium"
    encoder = sys.argv[7] if len(sys.argv) > 7 else "libx264"
    trim_start = _float_arg(8, 0.0)
    trim_end = _float_arg(9, 0.0)
    audio_extract_format = sys.argv[10] if len(sys.argv) > 10 else ""

    logger.info(
        f"🚀 Isolated compressor worker starting job_id={job_id} "
        f"(width={target_width}, bitrate={bitrate_kbps}kbps, crf={crf}, "
        f"preset={preset}, encoder={encoder}, "
        f"trim_start={trim_start}, trim_end={trim_end}, "
        f"audio_extract={audio_extract_format or 'none'})"
    )

    try:
        asyncio.run(
            process_compress_job(
                job_id, input_file_path, target_width, bitrate_kbps,
                crf, preset, encoder, trim_start, trim_end,
                audio_extract_format,
            )
        )
        logger.info(f"✅ Isolated compressor worker finished job_id={job_id}")
    except Exception as e:
        logger.error(
            f"❌ Isolated compressor worker failed for job_id={job_id}: {e}",
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
