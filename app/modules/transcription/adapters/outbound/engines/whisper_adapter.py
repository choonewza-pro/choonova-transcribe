"""
Whisper ASR Engine Outbound Adapter implementing ASREnginePort.
"""

from typing import Dict, Any
from app.modules.transcription.domain.ports import ASREnginePort
from app.whisper_engine import get_whisper_engine


class WhisperAdapter(ASREnginePort):
    """Whisper ASR Engine Outbound Adapter for English and multilingual audio."""

    def transcribe(self, audio_path: str, language: str = "en") -> Dict[str, Any]:
        engine = get_whisper_engine()
        text, timestamps = engine.transcribe_file(audio_path, language=language)
        return {
            "text": text,
            "timestamps": timestamps,
            "engine": "whisper",
        }
