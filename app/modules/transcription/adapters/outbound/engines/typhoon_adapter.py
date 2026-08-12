"""
Typhoon ASR Engine Outbound Adapter implementing ASREnginePort.
"""

from typing import Dict, Any
from app.modules.transcription.domain.ports import ASREnginePort
from app.asr_engine import get_asr_engine



class TyphoonAdapter(ASREnginePort):
    """Typhoon NeMo ASR Realtime Outbound Adapter."""

    def transcribe(self, audio_path: str, language: str = "th") -> Dict[str, Any]:
        engine = get_asr_engine()
        res = engine.transcribe_file(audio_path)
        return {
            "text": res.get("text", ""),
            "timestamps": res.get("timestamps", []),
            "engine": "typhoon",
        }
