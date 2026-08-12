"""
API Router for Real-time WebSocket Speech-to-Text Streaming.
Handles audio chunks and commands (INTERIM, COMMIT_SEGMENT, CLEAR) matching realtime.js frontend contract.
"""

import io
import os
import asyncio
import logging
import hmac
import subprocess
import tempfile
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.asr_engine import get_asr_engine
from app.cuda_utils import is_cuda_error, is_allocator_corruption
from app.engine_router import cuda_device_reset_all, reset_all
from app.core.config import GATEWAY_API_KEY

logger = logging.getLogger("choonova.realtime")
router = APIRouter(prefix="/v1/realtime", tags=["Realtime ASR"])

CUDA_RETRY_ATTEMPTS = 2
CUDA_RETRY_BACKOFF_SEC = 1.0


def remove_text_overlap(t1: str, t2: str) -> str:
    """
    Removes overlapping tail of t1 that matches the prefix of t2.
    Prevents duplicate words across streaming segment boundaries.
    """
    t1 = t1.strip()
    t2 = t2.strip()
    if not t1:
        return t2
    if not t2:
        return t1

    max_check = min(len(t1), len(t2), 60)
    best_match_len = 0

    for length in range(3, max_check + 1):
        if t1[-length:] == t2[:length]:
            best_match_len = length

    if best_match_len > 0:
        suffix_added = t2[best_match_len:].strip()
        return (t1 + " " + suffix_added).strip()

    return (t1 + " " + t2).strip()


def _convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    """
    Convert WebM/Opus audio bytes to 16kHz mono WAV in memory using ffmpeg pipes.

    libsndfile (the backend for librosa.load / soundfile.read) does not
    support the WebM container format. The browser's MediaRecorder API
    encodes audio as WebM/Opus, so we transcode to WAV in RAM via stdin/stdout
    pipes without touching the disk.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", "pipe:0",
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                "pipe:1",
            ],
            input=webm_bytes,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")[:200]
            logger.warning(f"ffmpeg in-memory WebM→WAV failed (rc={result.returncode}): {stderr}")
            return b""
        return result.stdout
    except Exception as e:
        logger.warning(f"WebM→WAV in-memory conversion error: {e}")
        return b""


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    api_key = websocket.cookies.get("typhoon_asr_api_key")
    if not api_key or not hmac.compare_digest(api_key.strip(), GATEWAY_API_KEY):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    logger.info("WebSocket client connected for real-time speech transcription.")

    engine = get_asr_engine()

    # Eagerly warm up the model in a background thread on WebSocket connect.
    # Without this, the model only loads on the first INTERIM/COMMIT command,
    # but the frontend waits for the model-loaded healthz signal before the
    # user starts speaking — causing a deadlock where neither side proceeds.
    asyncio.get_event_loop().run_in_executor(None, engine.load_model)

    audio_buffer = io.BytesIO()
    header_bytes = b""
    finalized_text = ""
    transcribe_lock = asyncio.Lock()
    MAX_BUFFER_BYTES = 480000

    async def _transcribe_bytes_async(b_data: bytes) -> str:
        if len(b_data) < 4096:
            return ""
        loop = asyncio.get_event_loop()

        # Convert WebM/Opus → WAV (16kHz mono) via ffmpeg because libsndfile
        # (used by librosa) does not support WebM containers.
        wav_data = await loop.run_in_executor(None, _convert_webm_to_wav, b_data)
        if not wav_data:
            return ""

        for attempt in range(1, CUDA_RETRY_ATTEMPTS + 1):
            try:
                res = await loop.run_in_executor(
                    None, engine.transcribe_bytes, wav_data, "stream.wav"
                )
                return res.get("text", "")
            except Exception as ex:
                if not is_cuda_error(ex):
                    logger.warning(f"Transcribe frame error (non-CUDA): {type(ex).__name__}: {ex}")
                    return ""
                if is_allocator_corruption(ex):
                    logger.warning(
                        f"Realtime transcribe hit CUDA allocator corruption: {ex}; "
                        "performing CUDA reset + model reload."
                    )
                    await loop.run_in_executor(None, cuda_device_reset_all)
                    try:
                        res = await loop.run_in_executor(
                            None, engine.transcribe_bytes, wav_data, "stream.wav"
                        )
                        return res.get("text", "")
                    except Exception as ex2:
                        logger.warning(f"Realtime retry after CUDA reset failed: {ex2}")
                        return ""
                if attempt == CUDA_RETRY_ATTEMPTS:
                    logger.warning(f"Realtime transcribe failed with CUDA error: {ex}")
                    await loop.run_in_executor(None, reset_all)
                    await loop.run_in_executor(None, engine.clear_cuda_cache)
                    try:
                        res = await loop.run_in_executor(
                            None, engine.transcribe_bytes, wav_data, "stream.wav"
                        )
                        return res.get("text", "")
                    except Exception:
                        return ""
                await loop.run_in_executor(None, engine.clear_cuda_cache)
                await asyncio.sleep(CUDA_RETRY_BACKOFF_SEC * attempt)
        return ""

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                logger.info("WebSocket client disconnected.")
                break

            if "bytes" in msg and msg["bytes"]:

                chunk = msg["bytes"]
                if not header_bytes:
                    header_bytes = chunk[:1024]
                audio_buffer.write(chunk)

                if audio_buffer.tell() > MAX_BUFFER_BYTES:
                    raw = audio_buffer.getvalue()
                    audio_buffer = io.BytesIO()
                    audio_buffer.write(header_bytes)
                    audio_buffer.write(raw[-MAX_BUFFER_BYTES:])

            elif "text" in msg:
                cmd = msg["text"].strip()
                if cmd == "CLEAR":
                    async with transcribe_lock:
                        finalized_text = ""
                        audio_buffer = io.BytesIO()
                        if header_bytes:
                            audio_buffer.write(header_bytes)

                elif cmd == "COMMIT_SEGMENT":
                    async with transcribe_lock:
                        b_data = audio_buffer.getvalue()
                        audio_buffer = io.BytesIO()
                        if header_bytes:
                            audio_buffer.write(header_bytes)

                        if len(b_data) > 4096:
                            text = await _transcribe_bytes_async(b_data)
                            if text:
                                finalized_text = remove_text_overlap(
                                    finalized_text, text
                                )
                            await websocket.send_json(
                                {
                                    "type": "final",
                                    "text": text,
                                    "fullText": finalized_text,
                                }
                            )

                elif cmd == "INTERIM":
                    if not transcribe_lock.locked():
                        async with transcribe_lock:
                            b_data = audio_buffer.getvalue()
                            # Cap audio at recent ~4-5s (120KB) + header for fast interim preview
                            if len(b_data) > 120000 and header_bytes:
                                b_data = header_bytes + b_data[-120000:]
                            if len(b_data) > 4096:
                                text = await _transcribe_bytes_async(b_data)
                                if text:
                                    preview = remove_text_overlap(finalized_text, text)
                                    await websocket.send_json(
                                        {
                                            "type": "partial",
                                            "text": text,
                                            "fullText": preview,
                                        }
                                    )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

