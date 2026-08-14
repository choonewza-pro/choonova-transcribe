import logging
from typing import Any, Dict, Optional

from app.config import SUPPORTED_LANGUAGES
from app.asr_engine import engine
from app.whisper_engine import whisper_engine

logger = logging.getLogger("engine-router")


def get_engines_state() -> Dict[str, str]:
    """
    Current residency state of both engines: 'loading' | 'loaded' | 'idle'.
    Also checks active background jobs to accurately reflect models loaded in isolated workers.
    """
    typhoon_state = engine.get_state()
    whisper_state = whisper_engine.get_state()

    # Check background workers
    try:
        from app.core.db import get_db_connection
        import sqlite3
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT language, current_stage FROM jobs WHERE status = 'processing'")
            for row in cursor.fetchall():
                lang = row["language"]
                stage = row["current_stage"]
                target = "typhoon" if lang == "th" else "whisper"
                
                if stage == "Loading Model onto VRAM":
                    if target == "typhoon" and typhoon_state != "loaded":
                        typhoon_state = "loading"
                    elif target == "whisper" and whisper_state != "loaded":
                        whisper_state = "loading"
                elif stage in ("Transcribing", "Finalizing"):
                    if target == "typhoon":
                        typhoon_state = "loaded"
                    elif target == "whisper":
                        whisper_state = "loaded"
    except Exception as e:
        logger.debug(f"Failed to fetch active job status for engine states: {e}")

    return {
        "typhoon": typhoon_state,
        "whisper": whisper_state,
    }


def apply_model_mode(mode: str) -> Dict[str, str]:
    """
    Apply a load-mode change at runtime.
      - 'always': eagerly load both engines so they are warm and resident.
      - 'idle':   leave them alone; the idle reaper will unload on timeout.
    Returns the engines state after applying.
    """
    if mode == "always":
        engine.load_model()
        whisper_engine.load_model()
    return get_engines_state()


def unload_if_idle_all(timeout_sec: float) -> bool:
    """
    Unload any engine that has been idle past timeout_sec. Returns True if at
    least one model was unloaded (used for logging cadence).
    """
    unloaded = False
    if engine.unload_if_idle(timeout_sec):
        unloaded = True
    if whisper_engine.unload_if_idle(timeout_sec):
        unloaded = True
    return unloaded


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
    task: str = "transcribe",
    temperature: Optional[float] = None,
    initial_prompt: Optional[str] = None,
    hotwords: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Route a transcription/translation request to the appropriate engine:
      - task='translate' -> Whisper (translates speech into English text)
      - 'th' (transcribe) -> Typhoon ASR (Thai-only, fast, streaming-friendly)
      - 'en'/'auto' (transcribe) -> Whisper
    """
    lang = normalize_language(language) if language else "th"

    if task == "translate":
        return whisper_engine.transcribe_file(
            audio_path,
            language=lang,
            with_timestamps=with_timestamps,
            task="translate",
            temperature=temperature,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
        )

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
        task="transcribe",
        temperature=temperature,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
    )


def transcribe_bytes(
    audio_bytes: bytes,
    filename_hint: str = "audio.wav",
    language: str = "th",
    with_timestamps: bool = False,
    task: str = "transcribe",
    temperature: Optional[float] = None,
    initial_prompt: Optional[str] = None,
    hotwords: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Route a raw-bytes transcription/translation request to the appropriate engine.
    """
    lang = normalize_language(language) if language else "th"

    if task == "translate":
        return whisper_engine.transcribe_bytes(
            audio_bytes,
            filename_hint=filename_hint,
            language=lang,
            with_timestamps=with_timestamps,
            task="translate",
            temperature=temperature,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
        )

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
        task="transcribe",
        temperature=temperature,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
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
