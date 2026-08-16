"""
WhisperX Adapter for ChooNova Transcribe.
Used in Path 4 (English / Auto + Diarization) providing Forced Phoneme Alignment
and PyAnnote Diarization integration.
"""

import os
import gc
import time
import logging
from typing import List, Dict, Any, Optional

from app.core.config import (
    DEVICE,
    HF_TOKEN,
    WHISPERX_MODEL,
    WHISPER_COMPUTE_TYPE,
    DIARIZATION_MODEL,
    DIARIZATION_MIN_SPEAKERS,
    DIARIZATION_MAX_SPEAKERS,
)

logger = logging.getLogger("whisperx-engine")


def clear_cuda_cache() -> None:
    try:
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
    except Exception:
        pass


class WhisperXDiarizer:
    """
    Manager for WhisperX (ASR + Forced Alignment + PyAnnote Diarization).
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ):
        self.model_name = model_name or WHISPERX_MODEL
        self.device = device or DEVICE
        self.compute_type = compute_type or WHISPER_COMPUTE_TYPE
        self._asr_model = None
        self._diarize_pipeline = None
        self._last_used_time = 0.0
        self._is_loading = False

    def is_loaded(self) -> bool:
        return self._asr_model is not None or self._diarize_pipeline is not None

    def get_state(self) -> str:
        if self._is_loading:
            return "loading"
        if self.is_loaded():
            return "loaded"
        return "idle"

    def load_asr_model(self) -> None:
        if self._asr_model is not None:
            return

        self._is_loading = True
        logger.info(
            f"Loading WhisperX ASR model ({self.model_name}) on device={self.device}, compute_type={self.compute_type}..."
        )
        start_t = time.time()
        try:
            import whisperx

            self._asr_model = whisperx.load_model(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._last_used_time = time.time()
            elapsed = time.time() - start_t
            logger.info(f"WhisperX ASR model loaded successfully in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Failed to load WhisperX ASR model: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize WhisperX ASR model: {e}") from e
        finally:
            self._is_loading = False

    def load_diarize_pipeline(self) -> None:
        if self._diarize_pipeline is not None:
            return

        if not HF_TOKEN:
            raise ValueError(
                "HF_TOKEN is required for WhisperX Speaker Diarization. "
                "Please set HF_TOKEN in your .env file."
            )

        logger.info(f"Loading WhisperX Diarization Pipeline ({DIARIZATION_MODEL}) on device={self.device}...")
        start_t = time.time()
        try:
            import whisperx

            self._diarize_pipeline = whisperx.DiarizationPipeline(
                model_name=DIARIZATION_MODEL,
                use_auth_token=HF_TOKEN,
                device=self.device,
            )
            self._last_used_time = time.time()
            elapsed = time.time() - start_t
            logger.info(f"WhisperX Diarization Pipeline loaded successfully in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Failed to load WhisperX Diarization Pipeline: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize WhisperX Diarization Pipeline: {e}") from e

    def transcribe_and_diarize(
        self,
        audio_path: str,
        language: Optional[str] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run WhisperX full pipeline: Transcribe -> Forced Alignment (with fallback) -> Diarize -> Assign Speakers.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        import whisperx

        self.load_asr_model()
        self.load_diarize_pipeline()
        self._last_used_time = time.time()

        logger.info(f"Loading audio for WhisperX: {audio_path}")
        audio = whisperx.load_audio(audio_path)

        # 1. ASR Transcribe
        batch_size = 16
        lang_arg = language if language and language != "auto" else None
        logger.info(f"Step 1: WhisperX Transcribe (lang={lang_arg}, batch_size={batch_size})")
        start_t = time.time()
        result = self._asr_model.transcribe(audio, batch_size=batch_size, language=lang_arg, task="transcribe")
        detected_lang = result.get("language", language or "en")
        logger.info(f"ASR step finished in {time.time() - start_t:.2f}s (detected_lang={detected_lang})")

        # 2. Forced Alignment (with Graceful Fallback)
        start_t = time.time()
        try:
            logger.info(f"Step 2: WhisperX Alignment for language '{detected_lang}'")
            model_a, metadata = whisperx.load_align_model(
                language_code=detected_lang, device=self.device
            )
            result = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )
            logger.info(f"Alignment step finished in {time.time() - start_t:.2f}s")
        except Exception as e:
            logger.warning(
                f"WhisperX alignment skipped for language '{detected_lang}' (fallback to raw segments): {e}"
            )

        # 3. Speaker Diarization
        diarize_kwargs = {}
        if num_speakers is not None and num_speakers > 0:
            diarize_kwargs["num_speakers"] = num_speakers
        else:
            min_spk = min_speakers if min_speakers is not None else DIARIZATION_MIN_SPEAKERS
            max_spk = max_speakers if max_speakers is not None else DIARIZATION_MAX_SPEAKERS
            if min_spk is not None and min_spk > 0:
                diarize_kwargs["min_speakers"] = min_spk
            if max_spk is not None and max_spk > 0:
                diarize_kwargs["max_speakers"] = max_spk

        logger.info(f"Step 3: WhisperX Diarization (kwargs={diarize_kwargs})")
        start_t = time.time()
        diarize_segments = self._diarize_pipeline(audio, **diarize_kwargs)
        logger.info(f"Diarization step finished in {time.time() - start_t:.2f}s")

        # 4. Assign Word Speakers
        logger.info("Step 4: Assigning word speakers...")
        result = whisperx.assign_word_speakers(diarize_segments, result)

        # 5. Format Standardized Output Payload
        raw_segments = result.get("segments", [])
        formatted_segments = []
        turn_text_parts = []
        current_speaker = None
        current_speaker_texts = []

        for seg in raw_segments:
            seg_start = float(seg.get("start", 0.0))
            seg_end = float(seg.get("end", 0.0))
            seg_text = seg.get("text", "").strip()
            seg_speaker = seg.get("speaker", "UNKNOWN")

            if not seg_text:
                continue

            formatted_segments.append(
                {
                    "start": round(seg_start, 3),
                    "end": round(seg_end, 3),
                    "text": seg_text,
                    "word": seg_text,
                    "speaker": seg_speaker,
                }
            )

            # Build formatted speaker text
            if current_speaker is None:
                current_speaker = seg_speaker
                current_speaker_texts = [seg_text]
            elif seg_speaker == current_speaker:
                current_speaker_texts.append(seg_text)
            else:
                turn_text_parts.append(f"[{current_speaker}]: {' '.join(current_speaker_texts)}")
                current_speaker = seg_speaker
                current_speaker_texts = [seg_text]

        if current_speaker is not None and current_speaker_texts:
            turn_text_parts.append(f"[{current_speaker}]: {' '.join(current_speaker_texts)}")

        formatted_full_text = "\n\n".join(turn_text_parts) if turn_text_parts else " ".join([s["text"] for s in formatted_segments])

        return {
            "text": formatted_full_text,
            "segments": formatted_segments,
            "language": detected_lang,
        }

    def reset(self) -> None:
        """
        Unload WhisperX models from VRAM and clear CUDA cache.
        """
        if self._asr_model is not None or self._diarize_pipeline is not None:
            logger.info("Unloading WhisperX models from memory...")
            self._asr_model = None
            self._diarize_pipeline = None
            gc.collect()
            clear_cuda_cache()

    def unload_if_idle(self, timeout_sec: float) -> bool:
        """
        Unload models if idle past timeout_sec. Returns True if unloaded.
        """
        if not self.is_loaded():
            return False

        idle_time = time.time() - self._last_used_time
        if idle_time >= timeout_sec:
            logger.info(f"WhisperX engine idle for {idle_time:.1f}s (timeout={timeout_sec}s); unloading.")
            self.reset()
            return True
        return False


_whisperx_instance: Optional[WhisperXDiarizer] = None


def get_whisperx_diarizer() -> WhisperXDiarizer:
    global _whisperx_instance
    if _whisperx_instance is None:
        _whisperx_instance = WhisperXDiarizer()
    return _whisperx_instance


def transcribe_and_diarize_whisperx(
    audio_path: str,
    language: Optional[str] = None,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> Dict[str, Any]:
    diarizer = get_whisperx_diarizer()
    return diarizer.transcribe_and_diarize(
        audio_path,
        language=language,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )
