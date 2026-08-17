"""
Inbound Worker Adapter for synchronous inline transcription subprocess.

Runs ONE inline /v1/audio/transcribe request in an isolated process so the
parent can terminate it on client cancel, freeing GPU/CPU immediately.
The transcription result is written as JSON to a file (parsed by the parent).

Usage:
    python -m app.run_inline_transcribe <input_audio_path> <language> \
        <with_timestamps> <model> <num_speakers> <min_speakers> \
        <max_speakers> <enable_diarization> <output_json_path>
"""

import sys
import os
import json
import time
import logging

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("choonova-inline-transcription-worker")


def _parse_int(value: str) -> int | None:
    if value in ("none", "None", ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes")


def _strip_word_level(segments: list) -> list:
    """Drop per-word fields from speaker-grouped segments.

    Diarization internally requires word timestamps to attribute words to
    speakers, but when the caller asked for no word-level output
    (with_timestamps=false) the response must not carry that data.
    Speaker turn boundaries and text survive.
    """
    return [
        {k: v for k, v in seg.items() if k not in ("word", "words")}
        for seg in segments
    ]


def run_transcription(
    input_path: str,
    language: str,
    with_timestamps: bool,
    model: str,
    num_speakers: int | None,
    min_speakers: int | None,
    max_speakers: int | None,
    enable_diarization: bool,
) -> dict:
    start_t = time.time()
    text = ""
    timestamps = []
    elapsed = 0.0
    duration = 0.0

    if enable_diarization:
        from app.config import DIARIZATION_ENABLED
        if not DIARIZATION_ENABLED:
            raise RuntimeError(
                "Speaker Diarization is disabled (DIARIZATION_ENABLED=false). "
                "Job cannot be processed."
            )
        from app.audio_utils import extract_audio_ffmpeg, get_audio_duration_ffmpeg
        temp_dir = os.path.dirname(input_path)
        temp_wav_path = os.path.join(temp_dir, "diarization_input.wav")
        extract_audio_ffmpeg(input_path, temp_wav_path)

        if language == "th" and model == "thai-whisper":
            from app.engine_router import transcribe_file as router_transcribe_file
            from app.pyannote_engine import (
                diarize_audio,
                group_words_by_turns,
                reconstruct_thai_words,
            )

            res = router_transcribe_file(
                audio_path=input_path,
                language=language,
                with_timestamps=True,
            )
            text = res.get("text", "")
            segments = res.get("segments", [])
            words = reconstruct_thai_words(segments)
            turns = diarize_audio(
                temp_wav_path,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
            grouped = group_words_by_turns(words, turns)
            timestamps = grouped
            if grouped:
                text = "\n\n".join(f"[{s['speaker']}]: {s['text']}" for s in grouped)
        else:
            from app.whisperx_engine import transcribe_and_diarize_whisperx
            wx_res = transcribe_and_diarize_whisperx(
                temp_wav_path, language, num_speakers, min_speakers, max_speakers,
                model=model,
            )
            text = wx_res.get("text", "")
            timestamps = wx_res.get("segments", [])

        elapsed = time.time() - start_t
        duration = get_audio_duration_ffmpeg(input_path)
    else:
        from app.engine_router import transcribe_bytes as router_transcribe_bytes
        with open(input_path, "rb") as f:
            audio_bytes = f.read()
        res = router_transcribe_bytes(
            audio_bytes=audio_bytes,
            filename_hint=os.path.basename(input_path),
            language=language,
            with_timestamps=with_timestamps,
            model=model,
        )
        text = res.get("text", "")
        elapsed = float(res.get("elapsed", 0.0))
        duration = float(res.get("duration", 0.0))
        timestamps = res.get("timestamps", [])

    if enable_diarization and not with_timestamps:
        timestamps = _strip_word_level(timestamps)

    rtf = elapsed / duration if duration > 0 else 0.0
    return {
        "text": text,
        "elapsed_seconds": round(elapsed, 3),
        "duration_seconds": round(duration, 2),
        "rtf": round(rtf, 5),
        "timestamps": timestamps,
        "model": model,
    }


def main():
    if len(sys.argv) < 10:
        logger.error(
            "Usage: python -m app.run_inline_transcribe <input_audio_path> <language> "
            "<with_timestamps> <model> <num_speakers> <min_speakers> "
            "<max_speakers> <enable_diarization> <output_json_path>"
        )
        sys.exit(1)

    input_path = sys.argv[1]
    language = sys.argv[2]
    with_timestamps = _parse_bool(sys.argv[3])
    model = sys.argv[4]
    num_speakers = _parse_int(sys.argv[5])
    min_speakers = _parse_int(sys.argv[6])
    max_speakers = _parse_int(sys.argv[7])
    enable_diarization = _parse_bool(sys.argv[8])
    output_json_path = sys.argv[9]

    logger.info(
        f"🚀 Inline Transcribe worker starting: input={os.path.basename(input_path)} "
        f"lang={language} model={model} diar={enable_diarization}"
    )

    try:
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
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        logger.info("✅ Inline Transcribe worker finished")
    except Exception as e:
        logger.error(f"❌ Inline Transcribe worker failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()