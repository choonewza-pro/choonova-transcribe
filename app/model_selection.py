"""
Model-selection matrix for the transcription pipeline.

Pure validation logic (no framework or engine imports) so it can be unit-tested
in isolation without pulling in PyTorch/NeMo/faster-whisper/librosa.
"""

from typing import Optional

from app.config import SUPPORTED_LANGUAGES

SUPPORTED_MODELS = ("thai-whisper", "typhoon", "whisper", "whisperx", "whisperx-thai")

# Allowed transcription model per (language, enable_diarization) combination.
_MODEL_MATRIX = {
    ("th", False): {"thai-whisper", "typhoon", "whisper"},
    ("th", True): {"thai-whisper", "whisperx", "whisperx-thai"},
    ("en", False): {"whisper"},
    ("en", True): {"whisperx"},
    ("auto", False): {"whisper"},
    ("auto", True): {"whisperx"},
}


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


def resolve_transcription_model(
    language: str,
    enable_diarization: bool,
    model: Optional[str] = None,
) -> str:
    """
    Validate the requested transcription model against the language/diarization
    matrix and return the canonical (normalized) model id.

    Raises ValueError with an actionable message listing the allowed models.
    """
    lang = normalize_language(language) if language else "th"
    allowed = _MODEL_MATRIX.get((lang, bool(enable_diarization)), set())

    if not model:
        raise ValueError(
            f"model is required for language='{lang}'"
            + (" with diarization" if enable_diarization else "")
            + f". Allowed: {', '.join(sorted(allowed))}"
        )

    model_clean = model.strip().lower()
    if model_clean not in allowed:
        raise ValueError(
            f"model='{model}' is not supported for language='{lang}'"
            + (" with diarization" if enable_diarization else "")
            + f". Allowed: {', '.join(sorted(allowed))}"
        )
    return model_clean
