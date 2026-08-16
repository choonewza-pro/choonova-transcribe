import logging
from typing import Any, Dict, Optional

from app.asr_engine import engine
from app.whisper_engine import whisper_engine
from app.whisper_thai_engine import whisper_thai_engine
from app.model_selection import (
    SUPPORTED_MODELS,
    normalize_language,
    resolve_transcription_model,
)

logger = logging.getLogger("engine-router")


def get_engines_state() -> Dict[str, str]:
    """
    Current residency state of the engines: 'loading' | 'loaded' | 'idle'.
    Also checks active background jobs to accurately reflect models loaded in isolated workers.
    """
    typhoon_state = engine.get_state()
    whisper_state = whisper_engine.get_state()
    whisper_thai_state = whisper_thai_engine.get_state()

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
                target = "whisper_thai" if lang == "th" else "whisper"
                
                if stage == "Loading Model onto VRAM":
                    if target == "whisper_thai" and whisper_thai_state != "loaded":
                        whisper_thai_state = "loading"
                    elif target == "whisper" and whisper_state != "loaded":
                        whisper_state = "loading"
                elif stage in ("Transcribing", "Finalizing"):
                    if target == "whisper_thai":
                        whisper_thai_state = "loaded"
                    elif target == "whisper":
                        whisper_state = "loaded"
    except Exception as e:
        logger.debug(f"Failed to fetch active job status for engine states: {e}")

    return {
        "typhoon": typhoon_state,
        "whisper": whisper_state,
        "whisper_thai": whisper_thai_state,
    }


def apply_model_mode(mode: str) -> Dict[str, str]:
    """
    Apply a load-mode change at runtime.
      - 'always': eagerly load the engines so they are warm and resident.
      - 'idle':   leave them alone; the idle reaper will unload on timeout.
    Returns the engines state after applying.
    """
    if mode == "always":
        engine.load_model()
        whisper_engine.load_model()
        whisper_thai_engine.load_model()
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
    if whisper_thai_engine.unload_if_idle(timeout_sec):
        unloaded = True
    try:
        from app.whisperx_engine import get_whisperx_diarizer
        if get_whisperx_diarizer().unload_if_idle(timeout_sec):
            unloaded = True
    except Exception as e:
        logger.debug(f"Failed to check WhisperX idle state: {e}")
    return unloaded


def _rebuild_thai_word_timestamps(segments) -> list:
    """
    Merge faster-whisper character-level Thai tokens back into whole words.

    The Thai-tuned Whisper tokenizer emits one token per Thai character
    (including tone marks) because Thai has no inter-word spaces, so raw
    `timestamps` are character-level. `reconstruct_thai_words` re-tokenizes
    each segment's full text with PyThaiNLP ``newmm`` and walks the character
    tokens (which carry real timestamps) to give each word a real start/end.
    """
    from app.pyannote_engine import reconstruct_thai_words

    return reconstruct_thai_words(segments)


def transcribe_file(
    audio_path: str,
    language: str = "th",
    with_timestamps: bool = False,
    is_chunk: bool = False,
    temperature: Optional[float] = None,
    initial_prompt: Optional[str] = None,
    hotwords: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Route a transcription request to the appropriate engine:
      - model='thai-whisper'/'typhoon'/'whisper' -> explicit engine selection
      - 'th' (model=None) -> Thai-tuned Whisper (accurate Thai offline ASR + real word timestamps)
      - 'en'/'auto' (model=None) -> Whisper
    """
    lang = normalize_language(language) if language else "th"
    model_clean = (model or "").strip().lower() or None

    if model_clean == "typhoon":
        res = engine.transcribe_file(
            audio_path,
            with_timestamps=False,
            is_chunk=is_chunk,
        )
        res["model"] = "typhoon"
        return res

    if model_clean == "whisper":
        res = whisper_engine.transcribe_file(
            audio_path,
            language=lang,
            with_timestamps=with_timestamps,
            temperature=temperature,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
        )
        res["model"] = "whisper"
        return res

    if lang == "th":
        res = whisper_thai_engine.transcribe_file(
            audio_path,
            language="th",
            with_timestamps=with_timestamps,
        )
        if with_timestamps:
            res["timestamps"] = _rebuild_thai_word_timestamps(res.get("segments", []))
        res["model"] = model_clean or "thai-whisper"
        return res
    res = whisper_engine.transcribe_file(
        audio_path,
        language=lang,
        with_timestamps=with_timestamps,
        temperature=temperature,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
    )
    res["model"] = model_clean or "whisper"
    return res


def transcribe_bytes(
    audio_bytes: bytes,
    filename_hint: str = "audio.wav",
    language: str = "th",
    with_timestamps: bool = False,
    temperature: Optional[float] = None,
    initial_prompt: Optional[str] = None,
    hotwords: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Route a raw-bytes transcription request to the appropriate engine.
    """
    lang = normalize_language(language) if language else "th"
    model_clean = (model or "").strip().lower() or None

    if model_clean == "typhoon":
        res = engine.transcribe_bytes(
            audio_bytes,
            filename_hint=filename_hint,
            with_timestamps=False,
        )
        res["model"] = "typhoon"
        return res

    if model_clean == "whisper":
        res = whisper_engine.transcribe_bytes(
            audio_bytes,
            filename_hint=filename_hint,
            language=lang,
            with_timestamps=with_timestamps,
            temperature=temperature,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
        )
        res["model"] = "whisper"
        return res

    if lang == "th":
        res = whisper_thai_engine.transcribe_bytes(
            audio_bytes,
            filename_hint=filename_hint,
            language="th",
            with_timestamps=with_timestamps,
        )
        if with_timestamps:
            res["timestamps"] = _rebuild_thai_word_timestamps(res.get("segments", []))
        res["model"] = model_clean or "thai-whisper"
        return res
    res = whisper_engine.transcribe_bytes(
        audio_bytes,
        filename_hint=filename_hint,
        language=lang,
        with_timestamps=with_timestamps,
        temperature=temperature,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
    )
    res["model"] = model_clean or "whisper"
    return res


def reset_all() -> None:
    """
    Reset ALL engines. Must be used instead of engine.reset() after any
    cudaDeviceReset, which invalidates the entire CUDA context in the process
    and would leave the Whisper models referencing dead memory.
    """
    engine.reset()
    whisper_engine.reset()
    whisper_thai_engine.reset()
    try:
        from app.whisperx_engine import get_whisperx_diarizer
        get_whisperx_diarizer().reset()
    except Exception as e:
        logger.debug(f"Failed to reset WhisperX engine: {e}")


def cuda_device_reset_all() -> None:
    """
    Perform a full CUDA device reset and mark both engines for reload.
    """
    engine.cuda_device_reset()
    reset_all()
