import os
import time
import tempfile
import logging
import threading
from typing import Dict, Any, Optional
import torch
import librosa
import soundfile as sf
from app.config import (
    MODEL_PATH,
    DEVICE,
    TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC,
    TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC,
)
from app.text_utils import clean_text, split_into_words

logger = logging.getLogger("typhoon-asr-engine")
logging.basicConfig(level=logging.INFO)


class TyphoonASREngine:
    """
    Singleton wrapper for Typhoon ASR inference model matching the official SCB-10X implementation.
    """

    def __init__(self):
        self.device = DEVICE
        self.model_path = MODEL_PATH
        self._is_loaded = False
        self._is_loading = False
        self._model = None
        # Idle-unload bookkeeping (monotonic clock, survives clock changes).
        self._last_used = 0.0
        self._in_flight = 0
        # RLock so the recursive transcribe_file (auto-chunking) can re-enter.
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

        logger.info(f"🌪️ Loading Typhoon ASR model on device: {self.device.upper()}...")
        start_time = time.time()
        self._is_loading = True

        try:
            import nemo.collections.asr as nemo_asr

            # Check if local .nemo file exists, otherwise load from HuggingFace hub
            if os.path.exists(self.model_path) and os.path.isfile(self.model_path):
                logger.info(
                    f"Restoring Typhoon model from local file: {self.model_path}"
                )
                self._model = nemo_asr.models.ASRModel.restore_from(
                    restore_path=self.model_path, map_location=torch.device(self.device)
                )
            else:
                model_name = "scb10x/typhoon-asr-realtime"
                logger.info(f"Loading Typhoon model from HuggingFace Hub: {model_name}")
                self._model = nemo_asr.models.ASRModel.from_pretrained(
                    model_name=model_name, map_location=torch.device(self.device)
                )

            self._is_loaded = True
            elapsed = time.time() - start_time
            logger.info(f"✅ Typhoon ASR model loaded successfully in {elapsed:.2f}s.")
        except Exception as e:
            logger.error(f"❌ Failed to load Typhoon ASR model: {e}")
            # Fallback to typhoon_asr package if available
            try:
                import typhoon_asr

                self._is_loaded = True
                logger.info("Using typhoon_asr package as fallback loader.")
            except Exception as ex:
                logger.error(f"Fallback typhoon_asr failed: {ex}")
                raise e
        finally:
            self._is_loading = False

    def clear_cuda_cache(self) -> None:
        """
        Synchronize and release cached CUDA memory.
        Used to recover from transient CUDA driver errors between chunk transcriptions.

        NOTE: torch.cuda.empty_cache() must NOT be called here. Calling it between
        consecutive NeMo model.transcribe() calls is a documented crash trigger
        ("CUDA error: an illegal memory access" on the NEXT transcribe) because the
        FastConformer-Transducer decoder uses CUDA graphs that still reference the
        freed memory (NVIDIA-NeMo/NeMo issue #14727). PYTORCH_CUDA_ALLOC_CONF with
        expandable_segments:True already returns VRAM to the OS without it.
        """
        try:
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        except Exception as e:
            logger.warning(f"Failed to clear CUDA cache: {e}")

    def cuda_device_reset(self) -> None:
        """
        Fully destroy and rebuild the CUDA context for this process.

        This is the only recovery that resets PyTorch's CUDACachingAllocator
        internal state (e.g. after `!handles_.at(i) INTERNAL ASSERT FAILED at
        CUDACachingAllocator.cpp` corruption from many back-to-back NeMo
        transcribe() calls). It invalidates ALL CUDA tensors/streams/handles in
        this process, so the model MUST be reloaded afterwards.
        """
        if not torch.cuda.is_available():
            return
        try:
            logger.warning("Performing full CUDA device reset (cudaDeviceReset)...")
            torch.cuda.cudart().cudaDeviceReset()
        except Exception as e:
            logger.warning(f"cudaDeviceReset raised: {e}")
        try:
            torch.cuda.init()
        except Exception as e:
            logger.warning(f"torch.cuda.init after device reset raised: {e}")
        logger.warning("CUDA device reset complete.")

    def reset(self) -> None:
        """
        Force re-initialization of the model on the next transcribe call.
        Used as a last-resort recovery when a CUDA driver error leaves the model context unusable.
        """
        with self._lifecycle_lock:
            self._model = None
            self._is_loaded = False
            self._is_loading = False
        logger.warning("Typhoon ASR model reset; will reload on next transcribe.")

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
        # Model fully dropped -> CUDA graphs destroyed, so empty_cache is safe here
        # (unlike between consecutive transcribe() calls, see clear_cuda_cache docstring).
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"empty_cache after idle unload failed: {e}")
        logger.info(
            f"Typhoon ASR model unloaded after {idle_sec:.0f}s idle "
            f"(timeout {timeout_sec:.0f}s); VRAM released"
        )
        return True

    def prepare_audio(
        self, input_path: str, target_sr: int = 16000
    ) -> tuple[str, float]:
        """
        Prepares audio file matching developer's official prepare_audio logic:
        1. Loads audio via fast soundfile (with librosa fallback)
        2. Resamples to 16kHz if needed
        3. Normalizes peak amplitude
        4. Writes processed WAV (bypasses duplicate disk write if already 16kHz WAV)
        """
        try:
            y, sr = sf.read(input_path, dtype="float32")
        except Exception:
            y, sr = librosa.load(input_path, sr=None)

        if y is None or len(y) == 0:
            raise ValueError("Failed to load audio file or file is empty.")

        # Downmix multichannel (stereo) audio to mono. librosa.resample treats
        # the last axis as time, so a 2D (N, channels) array is pathologically
        # slow and keeps the wrong frame count (e.g. 48kHz stereo -> 3x duration).
        if y.ndim > 1:
            y = y.mean(axis=1)

        duration = len(y) / float(sr)

        # Fast path: If already 16kHz mono WAV, bypass duplicate temp file write
        if sr == target_sr and input_path.lower().endswith(".wav"):
            return input_path, duration

        if sr != target_sr:
            y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)

        # Peak normalization
        max_val = max(abs(y)) if len(y) > 0 else 1.0
        y = y / (max_val + 1e-8)

        processed_fd, processed_path = tempfile.mkstemp(
            suffix=".wav", prefix="processed_"
        )
        os.close(processed_fd)

        sf.write(processed_path, y, target_sr)
        return processed_path, duration

    def _extract_text(self, obj: Any) -> str:
        """
        Helper method to extract plain string text from NeMo Hypothesis or tuple objects.
        """
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        if hasattr(obj, "text"):
            return str(obj.text)
        if isinstance(obj, (list, tuple)) and len(obj) > 0:
            return self._extract_text(obj[0])
        return str(obj)

    def transcribe_file(
        self,
        audio_path: str,
        with_timestamps: bool = False,
        is_chunk: bool = False,
    ) -> Dict[str, Any]:
        """
        Transcribes an audio file path using Typhoon ASR model.
        Automatically chunks long audio exceeding MAX_CHUNK_DURATION_SEC.
        """
        with self._lifecycle_lock:
            self._last_used = time.monotonic()
            self._in_flight += 1
            if not self._is_loaded:
                self.load_model()
            model = self._model

        start_time = time.time()
        processed_file, audio_duration = self.prepare_audio(audio_path)

        try:
            # Auto-chunk long audio to avoid PyTorch CUDA Caching Allocator memory assertion errors.
            # Guarded by is_chunk flag to prevent infinite recursion.
            if not is_chunk and audio_duration > TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC:
                logger.info(
                    f"Audio duration ({audio_duration:.1f}s) exceeds max chunk limit ({TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC}s). "
                    f"Auto-chunking audio..."
                )
                from app.audio_utils import split_audio_silence, safe_delete_dir

                chunks_dir = tempfile.mkdtemp(prefix="auto_chunks_")
                try:
                    chunks = split_audio_silence(
                        processed_file,
                        chunks_dir,
                        target_chunk_sec=TRANSCRIBE_TYPHOON_TARGET_CHUNK_DURATION_SEC,
                        max_chunk_sec=TRANSCRIBE_TYPHOON_MAX_CHUNK_DURATION_SEC,
                    )
                    combined_texts = []
                    combined_timestamps = []

                    for chunk in chunks:
                        c_res = self.transcribe_file(
                            chunk["path"], with_timestamps=with_timestamps, is_chunk=True
                        )
                        c_text = c_res.get("text", "").strip()
                        if c_text:
                            combined_texts.append(c_text)
                        c_ts = c_res.get("timestamps", [])
                        c_offset = chunk.get("start_sec", 0.0)
                        for item in c_ts:
                            combined_timestamps.append(
                                {
                                    "word": item.get("word", ""),
                                    "start": round(
                                        float(item.get("start", 0.0)) + c_offset, 2
                                    ),
                                    "end": round(
                                        float(item.get("end", 0.0)) + c_offset, 2
                                    ),
                                }
                            )

                    processing_time = time.time() - start_time
                    return {
                        "text": " ".join(combined_texts),
                        "elapsed": processing_time,
                        "duration": audio_duration,
                        "timestamps": combined_timestamps,
                    }
                finally:
                    safe_delete_dir(chunks_dir)

            if model is not None:
                with torch.inference_mode():
                    transcriptions = model.transcribe(
                        audio=[processed_file], return_hypotheses=False
                    )
                # Surface any deferred device-side CUDA fault NOW as a catchable
                # Python exception in this request thread, instead of letting it
                # fire asynchronously during a later tensor destructor (which
                # escalates to an uncatchable C++ std::terminate that kills the
                # whole process).
                if self.device == "cuda" and torch.cuda.is_available():
                    torch.cuda.synchronize()
                processing_time = time.time() - start_time

                transcription = ""
                if transcriptions and len(transcriptions) > 0:
                    transcription = clean_text(self._extract_text(transcriptions[0]))

                timestamps = []
                if with_timestamps and transcription and audio_duration > 0:
                    words = split_into_words(transcription)
                    if words:
                        avg_dur = audio_duration / len(words)
                        for i, word in enumerate(words):
                            timestamps.append(
                                {
                                    "word": word,
                                    "start": round(i * avg_dur, 2),
                                    "end": round((i + 1) * avg_dur, 2),
                                }
                            )

                return {
                    "text": transcription,
                    "elapsed": processing_time,
                    "duration": audio_duration,
                    "timestamps": timestamps,
                }
            else:
                # Fallback to typhoon_asr package
                import typhoon_asr

                res = typhoon_asr.transcribe(
                    processed_file, with_timestamps=with_timestamps, device=self.device
                )
                processing_time = time.time() - start_time
                return {
                    "text": res.get("text", ""),
                    "elapsed": processing_time,
                    "duration": audio_duration,
                    "timestamps": res.get("timestamps", []),
                }
        finally:
            if os.path.exists(processed_file):
                os.remove(processed_file)
            with self._lifecycle_lock:
                self._in_flight -= 1
            self.clear_cuda_cache()


    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename_hint: str = "audio.wav",
        with_timestamps: bool = False,
    ) -> Dict[str, Any]:
        """
        Transcribes raw audio bytes.
        """
        suffix = os.path.splitext(filename_hint)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            return self.transcribe_file(tmp_path, with_timestamps=with_timestamps)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


# Global singleton instance
engine = TyphoonASREngine()


def get_asr_engine() -> TyphoonASREngine:
    """Returns the global Typhoon ASR engine singleton instance."""
    return engine

