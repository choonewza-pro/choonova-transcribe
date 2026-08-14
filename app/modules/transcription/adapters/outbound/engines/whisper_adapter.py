"""
Whisper ASR Engine Outbound Adapter implementing ASREnginePort.
"""

from typing import Dict, Any
from app.modules.transcription.domain.ports import ASREnginePort


class WhisperAdapter(ASREnginePort):
    """Whisper ASR Engine Outbound Adapter for English and multilingual audio."""

    def transcribe(self, audio_path: str, language: str = "en") -> Dict[str, Any]:
        from app.whisper_engine import get_whisper_engine
        engine = get_whisper_engine()
        res = engine.transcribe_file(audio_path, language=language)
        return {
            "text": res.get("text", ""),
            "timestamps": res.get("timestamps", []),
            "engine": "whisper",
        }
