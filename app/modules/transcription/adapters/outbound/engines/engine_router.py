"""
ASR Engine Router Outbound Adapter for dynamic language-based engine selection.
"""

from typing import Dict, Any
from app.modules.transcription.domain.ports import ASREnginePort
from app.modules.transcription.adapters.outbound.engines.typhoon_adapter import TyphoonAdapter
from app.modules.transcription.adapters.outbound.engines.whisper_adapter import WhisperAdapter


class EngineRouterAdapter(ASREnginePort):
    """Routes transcription calls to Typhoon (Thai) or Whisper (English/Auto)."""

    def __init__(self):
        self.typhoon = TyphoonAdapter()
        self.whisper = WhisperAdapter()

    def transcribe(self, audio_path: str, language: str = "th") -> Dict[str, Any]:
        lang_clean = (language or "th").strip().lower()

        if lang_clean == "th":
            return self.typhoon.transcribe(audio_path, language="th")
        else:
            # 'en', 'auto', or any other language defaults to Whisper
            return self.whisper.transcribe(audio_path, language=lang_clean)
