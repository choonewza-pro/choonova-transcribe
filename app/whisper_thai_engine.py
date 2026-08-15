"""
Thai-tuned faster-whisper (CT2) engine for the Thai offline transcription path.

Replaces Typhoon ASR Realtime (`scb10x/typhoon-asr-realtime`) which, despite its
name, is a low-latency streaming FastConformer-Transducer whose TVSpeech CER
(9.99%) lags Whisper-based Thai models (6.3-6.9%). The Thai-tuned Whisper also
emits REAL word timestamps, which the speaker-diarization merge needs.

Typhoon remains the engine for the WebSocket/realtime path.
"""

import os
import logging

from app.core.config import (
    DEVICE,
    WHISPER_THAI_MODEL,
    WHISPER_THAI_COMPUTE_TYPE,
    SERVICE_DIR,
)
from app.whisper_engine import WhisperEngine

logger = logging.getLogger("whisper-thai-engine")


def resolve_thai_model_name() -> str:
    """
    Prefer a locally-baked copy of the CT2 model under `models/whisper-<name>`
    (same bind-mount trick as Typhoon's MODEL_PATH) so no HuggingFace download
    is needed at load time. Falls back to the HF repo id when absent.
    """
    base_name = WHISPER_THAI_MODEL.split("/")[-1]
    local_candidates = [
        os.path.join(SERVICE_DIR, "models", base_name),
        os.path.join(SERVICE_DIR, "models", f"whisper-{base_name}"),
    ]
    for candidate in local_candidates:
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "model.bin")):
            logger.info(f"Using local Thai Whisper model at: {candidate}")
            return candidate
    logger.info(f"Local Thai Whisper model not found; falling back to HF repo: {WHISPER_THAI_MODEL}")
    return WHISPER_THAI_MODEL


# condition_on_previous_text=False is the WhisperX-recommended long-form setting:
# it suppresses the "repetition / hallucination" failure mode that plagued
# the Thai offline path (e.g. "นางนางนาง...", "สายนางนางนางไง...").
whisper_thai_engine = WhisperEngine(
    model_name=resolve_thai_model_name(),
    compute_type=WHISPER_THAI_COMPUTE_TYPE,
    condition_on_prev_text=False,
)


def get_whisper_thai_engine() -> WhisperEngine:
    """Returns the global Thai-tuned Whisper engine singleton instance."""
    return whisper_thai_engine
