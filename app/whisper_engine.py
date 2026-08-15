import os
import time
import tempfile
import logging
import threading
from typing import Dict, Any, Optional

from app.config import DEVICE, WHISPER_MODEL, WHISPER_COMPUTE_TYPE

logger = logging.getLogger("whisper-engine")
logging.basicConfig(level=logging.INFO)


class WhisperEngine:
    """
    Singleton wrapper for the faster-whisper (CTranslate2) model.

    Used as a secondary engine for English / Thai-English mixed audio where
    Typhoon ASR (Thai-only) falls short. Supports explicit 'en' or auto-detected
    language, and emits real word-level timestamps.
    """

    def __init__(
        self,
        model_name: str = WHISPER_MODEL,
        compute_type: str = WHISPER_COMPUTE_TYPE,
        condition_on_prev_text: bool = True,
    ):
        self.device = DEVICE
        self.model_name = model_name
        self.compute_type = compute_type
        self.condition_on_prev_text = condition_on_prev_text
        self._is_loaded = False
        self._is_loading = False
        self._model = None
        # Idle-unload bookkeeping (monotonic clock, survives clock changes).
        self._last_used = 0.0
        self._in_flight = 0
        self._lifecycle_lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def get_state(self) -> str:
        """
        Model residency state for UI/dashboard: 'loading' | 'loaded' | 'idle'.
        """
        if self._is_loading:
            return "loading"
        if self.is_loaded:
            return "loaded"
        return "idle"

    def load_model(self):
        if self._is_loaded:
            return

        logger.info(
            f"🕊️ Loading Whisper model '{self.model_name}' on device: "
            f"{self.device.upper()} (compute_type={self.compute_type})..."
        )
        start_time = time.time()
        self._is_loading = True

        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._is_loaded = True
            elapsed = time.time() - start_time
            logger.info(f"✅ Whisper model loaded successfully in {elapsed:.2f}s.")
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            raise
        finally:
            self._is_loading = False

    def reset(self) -> None:
        """
        Drop the model so the next transcribe call reloads it fresh.
        Required after a full CUDA device reset (cudaDeviceReset) which
        invalidates all CUDA context in the process.
        """
        with self._lifecycle_lock:
            self._model = None
            self._is_loaded = False
            self._is_loading = False
        logger.warning("Whisper model reset; will reload on next transcribe.")

    def unload_if_idle(self, timeout_sec: float) -> bool:
        """
        Unload the model from VRAM if it has been idle longer than timeout_sec.
        Only safe when no transcribe is currently in-flight; guarded by the
        lifecycle lock. Returns True if the model was unloaded.
        """
        with self._lifecycle_lock:
            if not self.is_loaded:
                return False
            if self._in_flight > 0:
                return False
            idle_sec = time.monotonic() - self._last_used
            if idle_sec < timeout_sec:
                return False
            self._model = None
            self._is_loaded = False
            self._is_loading = False
        # CTranslate2 releases GPU memory when the model object is freed.
        logger.info(
            f"Whisper model unloaded after {idle_sec:.0f}s idle "
            f"(timeout {timeout_sec:.0f}s); VRAM released"
        )
        return True

    def clear_cuda_cache(self) -> None:
        """
        Release model-internal memory without touching the CUDA context.
        Kept for API parity with the Typhoon engine.
        """
        try:
            if self._model is not None:
                self._model = None
                self._is_loaded = False
        except Exception as e:
            logger.warning(f"Failed to clear Whisper cache: {e}")

    def transcribe_file(
        self,
        audio_path: str,
        language: str = "auto",
        with_timestamps: bool = False,
        temperature: Optional[float] = None,
        initial_prompt: Optional[str] = None,
        hotwords: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using the Whisper model.

        language: 'en' forces English, 'auto' uses Whisper's language detection
        (handles Thai, English, and Thai-English mixed content).
        """
        with self._lifecycle_lock:
            self._last_used = time.monotonic()
            self._in_flight += 1
            if not self._is_loaded:
                self.load_model()
            model = self._model

        start_time = time.time()
        try:
            whisper_lang = "en" if language == "en" else ("th" if language == "th" else None)
            if language == "auto":
                whisper_lang = None

            transcribe_kwargs = {
                "language": whisper_lang,
                "task": "transcribe",
                "word_timestamps": with_timestamps,
                "vad_filter": True,
                "condition_on_previous_text": self.condition_on_prev_text,
            }
            if temperature is not None:
                transcribe_kwargs["temperature"] = temperature
            if initial_prompt:
                transcribe_kwargs["initial_prompt"] = initial_prompt
            if hotwords:
                try:
                    transcribe_kwargs["hotwords"] = hotwords
                except TypeError:
                    if not initial_prompt:
                        transcribe_kwargs["initial_prompt"] = hotwords

            segments, info = model.transcribe(audio_path, **transcribe_kwargs)
            duration = float(info.duration or 0.0)
            detected_language = getattr(info, "language", language) or language

            combined_text = []
            timestamps = []
            segments_detail = []
            for segment in segments:
                text = (segment.text or "").strip()
                if text:
                    combined_text.append(text)
                seg_words = []
                if with_timestamps:
                    for word in getattr(segment, "words", None) or []:
                        w_text = (word.word or "").strip()
                        if w_text:
                            w_item = {
                                "word": w_text,
                                "start": round(float(word.start), 2),
                                "end": round(float(word.end), 2),
                            }
                            timestamps.append(w_item)
                            seg_words.append(w_item)

                segments_detail.append({
                    "id": getattr(segment, "id", len(segments_detail)),
                    "seek": getattr(segment, "seek", 0),
                    "start": round(float(segment.start), 2),
                    "end": round(float(segment.end), 2),
                    "text": text,
                    "tokens": getattr(segment, "tokens", []),
                    "temperature": getattr(segment, "temperature", 0.0),
                    "avg_logprob": getattr(segment, "avg_logprob", 0.0),
                    "compression_ratio": getattr(segment, "compression_ratio", 0.0),
                    "no_speech_prob": getattr(segment, "no_speech_prob", 0.0),
                    "words": seg_words if with_timestamps else None,
                })

            processing_time = time.time() - start_time
            return {
                "text": " ".join(combined_text),
                "elapsed": processing_time,
                "duration": duration,
                "language": detected_language,
                "timestamps": timestamps,
                "segments": segments_detail,
            }
        except Exception as e:
            logger.error(f"Whisper transcribe failed: {e}")
            raise
        finally:
            with self._lifecycle_lock:
                self._in_flight -= 1

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename_hint: str = "audio.wav",
        language: str = "auto",
        with_timestamps: bool = False,
        temperature: Optional[float] = None,
        initial_prompt: Optional[str] = None,
        hotwords: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe raw audio bytes.
        """
        suffix = os.path.splitext(filename_hint)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            return self.transcribe_file(
                tmp_path,
                language=language,
                with_timestamps=with_timestamps,
                temperature=temperature,
                initial_prompt=initial_prompt,
                hotwords=hotwords,
            )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# Global singleton instance
whisper_engine = WhisperEngine()


def get_whisper_engine() -> WhisperEngine:
    """Returns the global Whisper engine singleton instance."""
    return whisper_engine

