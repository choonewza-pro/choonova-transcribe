"""
OpenAI-compatible response and error formatters for Whisper API endpoints.
Provides standard SubRip (SRT), WebVTT (VTT), JSON, verbose_json, and OpenAI error responses.
"""

import math
from typing import Optional, List, Dict, Any
from fastapi.responses import JSONResponse

from app.schemas import (
    OpenAITranscriptionWord,
    OpenAITranscriptionSegment,
    OpenAITranscriptionVerboseJsonResponse,
    OpenAIErrorDetail,
    OpenAIErrorResponse,
)


def format_timestamp(seconds: float, decimal_separator: str = ",") -> str:
    """
    Format seconds into HH:MM:SS,mmm or HH:MM:SS.mmm format.
    """
    if seconds is None or math.isnan(seconds):
        seconds = 0.0

    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999

    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_separator}{millis:03d}"


def create_openai_error(
    status_code: int,
    message: str,
    error_type: str = "invalid_request_error",
    param: Optional[str] = None,
    code: Optional[str] = None,
) -> JSONResponse:
    """Create OpenAI-compatible JSON error response."""
    error_response = OpenAIErrorResponse(
        error=OpenAIErrorDetail(
            message=message,
            type=error_type,
            param=param,
            code=code,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(),
    )


def format_srt_response(result: Dict[str, Any]) -> str:
    """Format transcription result as standard SRT subtitle string."""
    segments = result.get("segments", [])
    if not segments and result.get("timestamps"):
        # Synthesize segments from word timestamps if segments array is missing
        segments = result.get("timestamps", [])

    srt_entries = []
    for idx, segment in enumerate(segments, 1):
        start_sec = float(segment.get("start", 0.0))
        end_sec = float(segment.get("end", 0.0))
        text = str(segment.get("text") or segment.get("word") or "").strip()
        speaker = segment.get("speaker")
        if speaker and not text.startswith(f"[{speaker}]"):
            text = f"[{speaker}]: {text}"

        start_time = format_timestamp(start_sec, ",")
        end_time = format_timestamp(end_sec, ",")
        srt_entries.append(f"{idx}\n{start_time} --> {end_time}\n{text}\n")

    return "\n".join(srt_entries).strip() + "\n" if srt_entries else ""


def format_vtt_response(result: Dict[str, Any]) -> str:
    """Format transcription result as standard WebVTT subtitle string."""
    segments = result.get("segments", [])
    if not segments and result.get("timestamps"):
        segments = result.get("timestamps", [])

    vtt_lines = ["WEBVTT\n"]
    for segment in segments:
        start_sec = float(segment.get("start", 0.0))
        end_sec = float(segment.get("end", 0.0))
        text = str(segment.get("text") or segment.get("word") or "").strip()
        speaker = segment.get("speaker")
        if speaker and not text.startswith(f"[{speaker}]"):
            text = f"[{speaker}]: {text}"

        start_time = format_timestamp(start_sec, ".")
        end_time = format_timestamp(end_sec, ".")
        vtt_lines.append(f"{start_time} --> {end_time}\n{text}\n")

    return "\n".join(vtt_lines).strip() + "\n"


def format_verbose_json_response(
    result: Dict[str, Any],
    task: str,
    language: str,
    duration: float,
    include_words: bool,
    include_segments: bool,
) -> OpenAITranscriptionVerboseJsonResponse:
    """Format result into OpenAI verbose_json response model."""
    full_text = str(result.get("text", "")).strip()

    segments: List[OpenAITranscriptionSegment] = []
    if include_segments:
        raw_segments = result.get("segments", [])
        for idx, seg in enumerate(raw_segments):
            start_s = float(seg.get("start", 0.0))
            end_s = float(seg.get("end", 0.0))
            text = str(seg.get("text") or seg.get("word") or "").strip()
            speaker = seg.get("speaker")
            if speaker and not text.startswith(f"[{speaker}]"):
                text = f"[{speaker}]: {text}"

            segments.append(
                OpenAITranscriptionSegment(
                    id=int(seg.get("id", idx)),
                    seek=int(seg.get("seek", int(start_s * 100))),
                    start=start_s,
                    end=end_s,
                    text=text,
                    tokens=seg.get("tokens", []),
                    temperature=float(seg.get("temperature", 0.0)),
                    avg_logprob=float(seg.get("avg_logprob", 0.0)),
                    compression_ratio=float(seg.get("compression_ratio", 0.0)),
                    no_speech_prob=float(seg.get("no_speech_prob", 0.0)),
                )
            )

    words: Optional[List[OpenAITranscriptionWord]] = None
    if include_words:
        words = []
        raw_timestamps = result.get("timestamps", [])
        if raw_timestamps:
            for ts in raw_timestamps:
                w_text = str(ts.get("word") or ts.get("text") or "").strip()
                if w_text:
                    words.append(
                        OpenAITranscriptionWord(
                            word=w_text,
                            start=float(ts.get("start", 0.0)),
                            end=float(ts.get("end", 0.0)),
                        )
                    )
        elif result.get("segments"):
            for seg in result.get("segments", []):
                for w in seg.get("words", []) or []:
                    w_text = str(w.get("word") or w.get("text") or "").strip()
                    if w_text:
                        words.append(
                            OpenAITranscriptionWord(
                                word=w_text,
                                start=float(w.get("start", 0.0)),
                                end=float(w.get("end", 0.0)),
                            )
                        )

    return OpenAITranscriptionVerboseJsonResponse(
        task=task,
        language=language,
        duration=duration,
        text=full_text,
        segments=segments,
        words=words if include_words else None,
    )
