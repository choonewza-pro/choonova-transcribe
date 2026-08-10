import logging
from typing import Any, Dict

from app.config import SUPPORTED_LANGUAGES
from app.asr_engine import engine
from app.whisper_engine import whisper_engine

logger = logging.getLogger("engine-router")


def normalize_language(language: str) -> str:
    """
    Validate/normalize the language parameter to one of ('th', 'en', 'auto').
    Raises ValueError for unsupported values.
    """
    lang = (language or "th").strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{language}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return lang


def transcribe_file(
    audio_path: str,
    language: str = "th",
    with_timestamps: bool = False,
    is_chunk: bool = False,
) -> Dict[str, Any]:
    """
    Route a transcription request to the appropriate engine:
      - 'th'       -> Typhoon ASR (Thai-only, fast, streaming-friendly)
      - 'en'/'auto' -> Whisper (English / Thai-English mixed, Latin script output)
    """
    lang = normalize_language(language)
    if lang == "th":
        return engine.transcribe_file(
            audio_path,
            with_timestamps=with_timestamps,
            is_chunk=is_chunk,
        )
    return whisper_engine.transcribe_file(
        audio_path,
        language=lang,
        with_timestamps=with_timestamps,
    )


def transcribe_bytes(
    audio_bytes: bytes,
    filename_hint: str = "audio.wav",
    language: str = "th",
    with_timestamps: bool = False,
) -> Dict[str, Any]:
    """
    Route a raw-bytes transcription request to the appropriate engine.
    """
    lang = normalize_language(language)
    if lang == "th":
        return engine.transcribe_bytes(
            audio_bytes,
            filename_hint=filename_hint,
            with_timestamps=with_timestamps,
        )
    return whisper_engine.transcribe_bytes(
        audio_bytes,
        filename_hint=filename_hint,
        language=lang,
        with_timestamps=with_timestamps,
    )


def reset_all() -> None:
    """
    Reset BOTH engines. Must be used instead of engine.reset() after any
    cudaDeviceReset, which invalidates the entire CUDA context in the process
    and would leave the Whisper model referencing dead memory.
    """
    engine.reset()
    whisper_engine.reset()


def cuda_device_reset_all() -> None:
    """
    Perform a full CUDA device reset and mark both engines for reload.
    """
    engine.cuda_device_reset()
    reset_all()
