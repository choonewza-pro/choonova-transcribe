"""
PyAnnote 3.1 Speaker Diarization Adapter for ChooNova Transcribe.
Used primarily in Path 3 (Thai + Diarization) alongside Typhoon ASR.
"""

import os
import gc
import time
import logging
from typing import List, Dict, Any, Optional

from app.core.config import (
    DEVICE,
    HF_TOKEN,
    SERVICE_DIR,
    DIARIZATION_MODEL,
    DIARIZATION_MIN_SPEAKERS,
    DIARIZATION_MAX_SPEAKERS,
)

logger = logging.getLogger("pyannote-engine")


def find_local_diarization_models() -> Optional[Dict[str, str]]:
    """
    Search for local segmentation and embedding models in known directories.
    Returns dict with {"segmentation": path, "embedding": path, "config": path} if found.
    """
    candidate_roots = [
        os.path.join(SERVICE_DIR, "models"),
        os.path.abspath("models"),
        "/app/models",
    ]
    for root in candidate_roots:
        if not os.path.exists(root):
            continue
        seg_path = os.path.join(root, "pyannote", "segmentation-3.0", "pytorch_model.bin")
        emb_path = os.path.join(root, "speechbrain", "spkrec-ecapa-voxceleb")
        config_path = os.path.join(root, "pyannote", "speaker-diarization-3.1", "config.yaml")
        if os.path.exists(seg_path) and os.path.exists(emb_path):
            return {
                "segmentation": seg_path,
                "embedding": emb_path,
                "config": config_path if os.path.exists(config_path) else None,
            }
    return None


def clear_cuda_cache() -> None:
    try:
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
    except Exception:
        pass


def merge_speaker_overlap(
    segments: List[Dict[str, Any]],
    diarization_turns: List[Dict[str, Any]],
    gap_tolerance_sec: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Merge ASR word/phrase segments with PyAnnote diarization turns using Maximum Overlap.
    Includes a Nearest-Neighbor fallback if a word falls inside a short pause gap between speech turns.

    :param segments: List of Dicts with {"start": float, "end": float, "text": str (or "word": str)}
    :param diarization_turns: List of Dicts with {"start": float, "end": float, "speaker": str}
    :param gap_tolerance_sec: Max gap in seconds to attach an unassigned segment to nearest speaker turn
    :return: Mutated/updated list of segments with "speaker" key added
    """
    if not segments:
        return []

    if not diarization_turns:
        for seg in segments:
            seg["speaker"] = "UNKNOWN"
        return segments

    for seg in segments:
        t_start = float(seg.get("start", 0.0))
        t_end = float(seg.get("end", 0.0))
        best_speaker = "UNKNOWN"
        max_overlap = 0.0

        for turn in diarization_turns:
            turn_start = float(turn["start"])
            turn_end = float(turn["end"])
            overlap = max(0.0, min(t_end, turn_end) - max(t_start, turn_start))
            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = turn["speaker"]

        # Fallback: If word falls inside a short silence/pause between turns, attach to closest turn
        if max_overlap == 0.0 and diarization_turns:
            closest_turn = min(
                diarization_turns,
                key=lambda t: min(
                    abs(float(t["start"]) - t_end),
                    abs(float(t["end"]) - t_start),
                ),
            )
            dist = min(
                abs(float(closest_turn["start"]) - t_end),
                abs(float(closest_turn["end"]) - t_start),
            )
            if dist <= gap_tolerance_sec:
                best_speaker = closest_turn["speaker"]

        seg["speaker"] = best_speaker

    return segments


def relabel_speakers_chronological(
    turns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Re-label speaker turns so that SPEAKER_00 is the first speaker to appear
    in the audio, SPEAKER_01 the second, and so on.

    PyAnnote assigns arbitrary cluster IDs (SPEAKER_00..N) that are NOT tied
    to the order speakers appear, so the same real person can be SPEAKER_01
    on one file and SPEAKER_00 on another. Renaming by first-appearance makes
    the output stable and predictable.
    """
    mapping: Dict[str, str] = {}
    ordered = sorted(turns, key=lambda t: float(t["start"]))
    for turn in ordered:
        old = turn["speaker"]
        if old not in mapping:
            mapping[old] = f"SPEAKER_{len(mapping):02d}"
        turn["speaker"] = mapping[old]
    return turns


def smooth_speaker_labels(
    segments: List[Dict[str, Any]],
    min_turn_sec: float = 1.5,
) -> List[Dict[str, Any]]:
    """
    Post-process merged word segments to reduce speaker flapping:

    - Words that could not be matched to any diarization turn ("UNKNOWN")
      are absorbed into the nearest known speaker turn.
    - Very short speaker blips (shorter than ``min_turn_sec``) sandwiched
      between two turns of the *same* speaker are snapped to that speaker.

    This only ever merges ambiguous/short runs — legitimate alternating
    A-B-A-B back-and-forth (different neighbors) is preserved.
    """
    if not segments:
        return segments

    runs = []
    for seg in segments:
        spk = str(seg.get("speaker") or "UNKNOWN")
        if runs and runs[-1]["speaker"] == spk:
            runs[-1]["end"] = float(seg.get("end", 0.0))
            runs[-1]["segs"].append(seg)
        else:
            runs.append(
                {
                    "speaker": spk,
                    "start": float(seg.get("start", 0.0)),
                    "end": float(seg.get("end", 0.0)),
                    "segs": [seg],
                }
            )

    for i, r in enumerate(runs):
        dur = r["end"] - r["start"]
        prev = runs[i - 1] if i > 0 else None
        nxt = runs[i + 1] if i < len(runs) - 1 else None

        if r["speaker"] == "UNKNOWN":
            candidates = [c for c in (prev, nxt) if c and c["speaker"] != "UNKNOWN"]
            if not candidates:
                continue
            target = min(
                candidates,
                key=lambda c: min(
                    abs(r["start"] - c["end"]), abs(c["start"] - r["end"])
                ),
            )
            for seg in r["segs"]:
                seg["speaker"] = target["speaker"]
        elif dur < min_turn_sec and prev and nxt and prev["speaker"] == nxt["speaker"]:
            if prev["speaker"] != r["speaker"]:
                for seg in r["segs"]:
                    seg["speaker"] = prev["speaker"]

    return segments


def group_speaker_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group continuous segments belonging to the same speaker into coherent speaker turn segments.
    """
    if not segments:
        return []

    smooth_speaker_labels(segments)

    grouped = []
    current_speaker = None
    current_text_parts = []
    current_start = None
    current_end = 0.0

    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        text = (seg.get("text") or seg.get("word") or "").strip()
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))

        if not text:
            continue

        if current_speaker is None:
            current_speaker = speaker
            current_start = start
            current_end = end
            current_text_parts = [text]
        elif speaker == current_speaker:
            current_text_parts.append(text)
            current_end = end
        else:
            grouped.append(
                {
                    "speaker": current_speaker,
                    "start": round(current_start, 3),
                    "end": round(current_end, 3),
                    "text": " ".join(current_text_parts),
                    "word": " ".join(current_text_parts),
                }
            )
            current_speaker = speaker
            current_start = start
            current_end = end
            current_text_parts = [text]

    if current_speaker is not None and current_text_parts:
        grouped.append(
            {
                "speaker": current_speaker,
                "start": round(current_start, 3),
                "end": round(current_end, 3),
                "text": " ".join(current_text_parts),
                "word": " ".join(current_text_parts),
            }
        )

    return grouped


def format_timestamp_srt(seconds: float) -> str:
    """Format seconds (e.g. 12.345) to SRT timestamp string: 00:00:12,345"""
    from datetime import timedelta
    if seconds < 0:
        seconds = 0.0
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt_subtitles(
    timestamps: List[Dict[str, Any]],
    max_words_per_cue: int = 8,
    max_gap_sec: float = 1.0,
) -> str:
    """
    Group continuous word/segment timestamps into SRT subtitle cues.
    Supports both word-level timestamps and speaker-grouped segments.
    """
    if not timestamps:
        return ""

    cues = []
    current_cue_words = []
    current_cue_start = None
    current_cue_speaker = None
    last_word_end = 0.0

    for item in timestamps:
        word = (item.get("word") or item.get("text") or "").strip()
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        speaker = item.get("speaker")

        if not word:
            continue

        if current_cue_start is None:
            current_cue_start = start
            current_cue_speaker = speaker

        is_long_gap = (start - last_word_end) > max_gap_sec if last_word_end > 0 else False
        is_max_words = len(current_cue_words) >= max_words_per_cue
        is_speaker_change = (
            speaker != current_cue_speaker if current_cue_speaker is not None and speaker is not None else False
        )

        if current_cue_words and (is_long_gap or is_max_words or is_speaker_change):
            cue_text = " ".join(current_cue_words)
            if current_cue_speaker and not cue_text.startswith("["):
                cue_text = f"[{current_cue_speaker}]: {cue_text}"
            cues.append(
                {
                    "start": current_cue_start,
                    "end": last_word_end,
                    "text": cue_text,
                }
            )
            current_cue_words = [word]
            current_cue_start = start
            current_cue_speaker = speaker
        else:
            current_cue_words.append(word)

        last_word_end = end

    if current_cue_words and current_cue_start is not None:
        cue_text = " ".join(current_cue_words)
        if current_cue_speaker and not cue_text.startswith("["):
            cue_text = f"[{current_cue_speaker}]: {cue_text}"
        cues.append(
            {
                "start": current_cue_start,
                "end": last_word_end,
                "text": cue_text,
            }
        )

    srt_lines = []
    for idx, cue in enumerate(cues, 1):
        start_str = format_timestamp_srt(cue["start"])
        end_str = format_timestamp_srt(cue["end"])
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{cue['text']}\n")

    return "\n".join(srt_lines)


class PyAnnoteDiarizer:
    """
    Singleton-friendly PyAnnote 3.1 Diarization Pipeline manager.
    Lazy-loads pyannote.audio to prevent unwanted VRAM allocation on process startup.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_name = model_name or DIARIZATION_MODEL
        self.device = device or DEVICE
        self._pipeline = None
        self._last_used_time = 0.0
        self._is_loading = False

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def get_state(self) -> str:
        if self._is_loading:
            return "loading"
        if self._pipeline is not None:
            return "loaded"
        return "idle"

    def load_model(self) -> None:
        """
        Lazy-load PyAnnote pipeline onto GPU/CPU context.
        Prioritizes local models from /models directory (offline),
        falling back to Hugging Face Hub if HF_TOKEN is configured.
        """
        if self._pipeline is not None:
            return

        self._is_loading = True
        start_t = time.time()

        try:
            import torch
            local_models = find_local_diarization_models()

            if local_models is not None:
                logger.info(
                    f"Loading PyAnnote Diarization from local models: "
                    f"segmentation={local_models['segmentation']}, embedding={local_models['embedding']} "
                    f"on device={self.device}..."
                )
                # Patch SpeechBrain 1.0+ compatibility for pyannote.audio
                try:
                    from speechbrain.inference.classifiers import EncoderClassifier
                    orig_from_hparams = getattr(EncoderClassifier, "_choonova_orig_from_hparams", None)
                    if orig_from_hparams is None:
                        orig_from_hparams = EncoderClassifier.from_hparams
                        EncoderClassifier._choonova_orig_from_hparams = orig_from_hparams

                    def _patched_from_hparams(*args, **kwargs):
                        if "use_auth_token" in kwargs:
                            tok = kwargs.pop("use_auth_token")
                            if tok is not None:
                                kwargs["token"] = tok
                        if "revision" in kwargs:
                            rev = kwargs.pop("revision")
                            if rev is not None:
                                kwargs["revision"] = rev
                        if "run_opts" in kwargs and isinstance(kwargs["run_opts"], dict) and "device" in kwargs["run_opts"]:
                            kwargs["run_opts"]["device"] = str(kwargs["run_opts"]["device"])
                        return orig_from_hparams(*args, **kwargs)

                    EncoderClassifier.from_hparams = _patched_from_hparams
                except Exception as e:
                    logger.warning(f"Could not patch SpeechBrain from_hparams: {e}")

                from pyannote.audio.pipelines.speaker_diarization import SpeakerDiarization
                import yaml

                pipeline = SpeakerDiarization(
                    segmentation=local_models["segmentation"],
                    embedding=local_models["embedding"],
                    clustering="AgglomerativeClustering",
                    embedding_batch_size=32,
                    embedding_exclude_overlap=True,
                    segmentation_batch_size=32,
                )

                params = {
                    "clustering": {"method": "centroid", "min_cluster_size": 12, "threshold": 0.7045654963945799},
                    "segmentation": {"min_duration_off": 0.0},
                }
                if local_models.get("config") and os.path.exists(local_models["config"]):
                    try:
                        with open(local_models["config"], "r", encoding="utf-8") as fp:
                            loaded_cfg = yaml.safe_load(fp)
                            if "params" in loaded_cfg:
                                params = loaded_cfg["params"]
                    except Exception as ex:
                        logger.warning(f"Could not read params from local config.yaml: {ex}")

                pipeline.instantiate(params)

                if self.device == "cuda" and torch.cuda.is_available():
                    pipeline.to(torch.device("cuda"))

                self._pipeline = pipeline
                self._last_used_time = time.time()
                elapsed = time.time() - start_t
                logger.info(f"PyAnnote Diarization loaded from local models successfully in {elapsed:.2f}s")
                return

            # Fallback to Hugging Face Hub download if local models not found
            if not HF_TOKEN:
                raise ValueError(
                    "Local PyAnnote models not found in models/pyannote and models/speechbrain, "
                    "and HF_TOKEN is not configured in .env.\n"
                    "Either place models in models/ folder or set HF_TOKEN in .env."
                )

            logger.info(f"Loading PyAnnote Diarization model from Hugging Face ({self.model_name}) on device={self.device}...")
            from pyannote.audio import Pipeline

            pipeline = Pipeline.from_pretrained(
                self.model_name,
                use_auth_token=HF_TOKEN,
            )

            if self.device == "cuda" and torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))

            self._pipeline = pipeline
            self._last_used_time = time.time()
            elapsed = time.time() - start_t
            logger.info(f"PyAnnote Diarization model loaded from HF successfully in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Failed to load PyAnnote model ({self.model_name}): {e}", exc_info=True)
            raise RuntimeError(
                f"Failed to initialize PyAnnote Diarization pipeline: {e}. "
                "Ensure local models exist in models/ folder or valid HF_TOKEN is provided."
            ) from e
        finally:
            self._is_loading = False

    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform speaker diarization on a single audio file.
        Returns a list of turn dicts: [{"start": float, "end": float, "speaker": str}]
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found for diarization: {audio_path}")

        self.load_model()
        self._last_used_time = time.time()

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

        logger.info(f"Running PyAnnote diarization on {audio_path} (kwargs={diarize_kwargs})")
        start_t = time.time()

        diarization_result = self._pipeline(audio_path, **diarize_kwargs)

        turns = []
        for turn, _, speaker in diarization_result.itertracks(yield_label=True):
            turns.append(
                {
                    "start": round(turn.start, 3),
                    "end": round(turn.end, 3),
                    "speaker": str(speaker),
                }
            )

        relabel_speakers_chronological(turns)

        elapsed = time.time() - start_t
        logger.info(f"PyAnnote diarization completed in {elapsed:.2f}s (Extracted {len(turns)} turns)")
        return turns

    def reset(self) -> None:
        """
        Unload pipeline from VRAM/RAM and clear CUDA memory cache.
        """
        if self._pipeline is not None:
            logger.info("Unloading PyAnnote Diarization model from memory...")
            self._pipeline = None
            gc.collect()
            clear_cuda_cache()

    def unload_if_idle(self, timeout_sec: float) -> bool:
        """
        Unload model if it has been idle past timeout_sec. Returns True if unloaded.
        """
        if self._pipeline is None:
            return False

        idle_time = time.time() - self._last_used_time
        if idle_time >= timeout_sec:
            logger.info(f"PyAnnote model idle for {idle_time:.1f}s (timeout={timeout_sec}s); unloading.")
            self.reset()
            return True
        return False


_diarizer_instance: Optional[PyAnnoteDiarizer] = None


def get_pyannote_diarizer() -> PyAnnoteDiarizer:
    global _diarizer_instance
    if _diarizer_instance is None:
        _diarizer_instance = PyAnnoteDiarizer()
    return _diarizer_instance


def diarize_audio(
    audio_path: str,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> List[Dict[str, Any]]:
    diarizer = get_pyannote_diarizer()
    return diarizer.diarize(
        audio_path,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )
