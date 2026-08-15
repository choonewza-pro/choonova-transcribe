"""
OpenAI-Compatible Audio API Endpoints for ChooNova Transcribe.
Provides standard drop-in replacement endpoints:
  - POST /v1/audio/transcriptions
  - GET  /v1/models
  - GET  /v1/models/{model_id}
"""

import os
import time
import logging
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, File, UploadFile, Form, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import (
    MAX_AUDIO_UPLOAD_SIZE_MB,
    MIN_FREE_DISK_GB,
    TEMP_JOBS_DIR,
)
from app.core.security import verify_api_key
from app.core.media_validator import validate_extension, validate_magic_bytes
from app.schemas import (
    ResponseFormat,
    TimestampGranularity,
    OpenAITranscriptionJsonResponse,
    OpenAITranscriptionVerboseJsonResponse,
)
from app.modules.transcription.application.openai_formatters import (
    format_srt_response,
    format_vtt_response,
    format_verbose_json_response,
    create_openai_error,
)
from app.audio_utils import check_disk_space

logger = logging.getLogger("openai-router")

router = APIRouter(tags=["OpenAI Compatible"])

SUPPORTED_OPENAI_MODELS = [
    {"id": "whisper-1", "object": "model", "created": 1677610602, "owned_by": "openai"},
    {"id": "whisper-large-v3-turbo", "object": "model", "created": 1700000000, "owned_by": "whisper"},
    {"id": "typhoon-asr", "object": "model", "created": 1700000000, "owned_by": "scb10x"},
    {"id": "typhoon", "object": "model", "created": 1700000000, "owned_by": "scb10x"},
]


def _resolve_model(model_name: Optional[str]) -> str:
    """Normalize model string to 'whisper' or 'typhoon'."""
    m = (model_name or "whisper-1").strip().lower()
    if "typhoon" in m:
        return "typhoon"
    return "whisper"


@router.post("/v1/audio/transcriptions")
async def create_transcription(
    request: Request,
    file: UploadFile = File(..., description="The audio file object (not file name) to transcribe."),
    model: str = Form("whisper-1", description="ID of the model to use (whisper-1, typhoon-asr, etc.)."),
    language: Optional[str] = Form(None, description="The language of the input audio (ISO-639-1 format e.g. 'th', 'en')."),
    prompt: Optional[str] = Form(None, description="An optional text to guide the model's style or continue a previous audio segment."),
    hotwords: Optional[str] = Form(None, description="Optional hotwords/phrases to bias transcription."),
    response_format: ResponseFormat = Form(ResponseFormat.JSON, description="The format of the transcript output."),
    temperature: float = Form(0.0, description="The sampling temperature, between 0 and 1."),
    authenticated: bool = Depends(verify_api_key),
):
    """
    Transcribes audio into the input language.
    OpenAI-compatible drop-in endpoint: POST /v1/audio/transcriptions
    """
    form_data = await request.form()
    timestamp_granularities = form_data.getlist("timestamp_granularities[]")
    if not timestamp_granularities:
        timestamp_granularities = []
    if response_format == ResponseFormat.VERBOSE_JSON and not timestamp_granularities:
        timestamp_granularities = ["segment"]

    return await _handle_audio_request(
        file=file,
        model=model,
        language=language,
        prompt=prompt,
        hotwords=hotwords,
        response_format=response_format,
        temperature=temperature,
        timestamp_granularities=timestamp_granularities,
    )


async def _handle_audio_request(
    file: UploadFile,
    model: str,
    language: Optional[str],
    prompt: Optional[str],
    hotwords: Optional[str],
    response_format: ResponseFormat,
    temperature: float,
    timestamp_granularities: List[str],
):
    """Internal handler for audio transcriptions."""
    if not file.filename:
        return create_openai_error(400, "Audio file must be provided.", param="file")

    try:
        validate_extension(file.filename)
    except Exception as e:
        return create_openai_error(400, f"Unsupported file format: {e}", param="file")

    if temperature is not None and (temperature < 0.0 or temperature > 1.0):
        return create_openai_error(400, "temperature must be between 0 and 1", param="temperature")

    if timestamp_granularities and response_format != ResponseFormat.VERBOSE_JSON:
        return create_openai_error(
            400,
            "timestamp_granularities is only supported when response_format='verbose_json'",
            param="timestamp_granularities",
        )

    resolved_engine = _resolve_model(model)
    target_lang = "auto"
    if language:
        lang_str = language.strip().lower()
        if lang_str in ("th", "thai"):
            target_lang = "th"
        elif lang_str in ("en", "english"):
            target_lang = "en"
        elif lang_str in ("auto", ""):
            target_lang = "auto"
        else:
            from app.config import SUPPORTED_LANGUAGES
            if lang_str not in SUPPORTED_LANGUAGES:
                return create_openai_error(
                    400,
                    f"Unsupported language '{language}'. Supported languages: {', '.join(SUPPORTED_LANGUAGES)}",
                    error_type="invalid_request_error",
                    param="language",
                    code="invalid_language",
                )
            target_lang = lang_str
    elif resolved_engine == "typhoon":
        target_lang = "th"

    # Disk check
    if not check_disk_space(TEMP_JOBS_DIR, MIN_FREE_DISK_GB):
        return create_openai_error(
            507,
            f"Insufficient disk space. At least {MIN_FREE_DISK_GB} GB free disk space is required.",
            error_type="server_error",
        )

    try:
        max_audio_bytes = int(MAX_AUDIO_UPLOAD_SIZE_MB * 1024 * 1024)
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > max_audio_bytes:
                return create_openai_error(
                    413,
                    f"File exceeds maximum upload size of {MAX_AUDIO_UPLOAD_SIZE_MB:.0f} MB",
                    error_type="invalid_request_error",
                    code="file_too_large",
                )
        content = bytes(content)
        validate_magic_bytes(content[:2048])

        with_timestamps = (
            response_format in (ResponseFormat.SRT, ResponseFormat.VTT, ResponseFormat.VERBOSE_JSON)
            or "word" in timestamp_granularities
        )

        from app.engine_router import transcribe_bytes as router_transcribe_bytes
        res = await asyncio.to_thread(
            router_transcribe_bytes,
            audio_bytes=content,
            filename_hint=file.filename,
            language=target_lang,
            with_timestamps=with_timestamps,
            temperature=temperature,
            initial_prompt=prompt,
            hotwords=hotwords,
        )

        full_text = str(res.get("text", "")).strip()
        duration = float(res.get("duration", 0.0))
        detected_lang = str(res.get("language") or target_lang or "en")

        if response_format == ResponseFormat.JSON:
            return JSONResponse(content={"text": full_text})

        elif response_format == ResponseFormat.TEXT:
            return PlainTextResponse(content=full_text, media_type="text/plain")

        elif response_format == ResponseFormat.SRT:
            srt_content = format_srt_response(res)
            return PlainTextResponse(content=srt_content, media_type="text/plain")

        elif response_format == ResponseFormat.VTT:
            vtt_content = format_vtt_response(res)
            return PlainTextResponse(content=vtt_content, media_type="text/vtt")

        elif response_format == ResponseFormat.VERBOSE_JSON:
            include_words = "word" in timestamp_granularities
            include_segments = "segment" in timestamp_granularities or not timestamp_granularities
            verbose_resp = format_verbose_json_response(
                result=res,
                task="transcribe",
                language=detected_lang,
                duration=duration,
                include_words=include_words,
                include_segments=include_segments,
            )
            return JSONResponse(content=verbose_resp.model_dump(exclude_none=True))

        return create_openai_error(400, f"Unsupported response format: {response_format}")

    except ValueError as e:
        logger.warning(f"OpenAI-compat validation error: {e}")
        return create_openai_error(
            400,
            str(e),
            error_type="invalid_request_error",
            param="language",
            code="invalid_request",
        )
    except HTTPException as e:
        return create_openai_error(
            e.status_code,
            str(e.detail),
            error_type="invalid_request_error" if e.status_code < 500 else "server_error",
        )
    except Exception as e:
        logger.error(f"OpenAI-compat transcription failed: {e}", exc_info=True)
        return create_openai_error(500, f"Internal server error: {e}", error_type="server_error")


@router.get("/v1/models")
async def list_models():
    """
    List available models.
    OpenAI-compatible endpoint: GET /v1/models
    """
    return {
        "object": "list",
        "data": SUPPORTED_OPENAI_MODELS,
    }


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    """
    Get details about a specific model.
    OpenAI-compatible endpoint: GET /v1/models/{model_id}
    """
    for m in SUPPORTED_OPENAI_MODELS:
        if m["id"] == model_id:
            return m

    return create_openai_error(
        404,
        f"Model '{model_id}' not found",
        error_type="invalid_request_error",
        code="model_not_found",
    )
