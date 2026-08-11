"""
API Router for Real-time WebSocket Speech-to-Text Streaming.
Enforces lightweight fast-path without DB mapping per audio chunk.
"""

import io
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.asr_engine import get_asr_engine
from app.cuda_utils import is_cuda_error, is_allocator_corruption
from app.engine_router import cuda_device_reset_all

logger = logging.getLogger("choonova.realtime")
router = APIRouter(prefix="/v1/realtime", tags=["Realtime ASR"])

CUDA_RETRY_ATTEMPTS = 2


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected for real-time speech transcription.")

    engine = get_asr_engine()
    audio_buffer = io.BytesIO()
    header_bytes = b""
    finalized_text = ""
    transcribe_lock = asyncio.Lock()
    MAX_BUFFER_BYTES = 480000

    async def _transcribe_bytes_async(b_data: bytes) -> str:
        if len(b_data) < 4096:
            return ""
        loop = asyncio.get_event_loop()
        for attempt in range(1, CUDA_RETRY_ATTEMPTS + 1):
            try:
                res = await loop.run_in_executor(
                    None, engine.transcribe_bytes, b_data, "stream.webm"
                )
                return res.get("text", "")
            except Exception as ex:
                if not is_cuda_error(ex):
                    logger.debug(f"Transcribe frame error (handled safely): {ex}")
                    return ""
                if is_allocator_corruption(ex):
                    logger.warning(
                        f"Realtime transcribe hit CUDA allocator corruption: {ex}; "
                        "performing CUDA reset + model reload."
                    )
                    await loop.run_in_executor(None, cuda_device_reset_all)
                    try:
                        res = await loop.run_in_executor(
                            None, engine.transcribe_bytes, b_data, "stream.webm"
                        )
                        return res.get("text", "")
                    except Exception as ex2:
                        logger.debug(f"Realtime retry failed: {ex2}")
                        return ""
                if attempt == CUDA_RETRY_ATTEMPTS:
                    logger.warning(f"Realtime transcribe failed with CUDA error: {ex}")
                    return ""
                await loop.run_in_executor(None, engine.clear_cuda_cache)
                await asyncio.sleep(0.2)
        return ""


    try:
        while True:
            msg = await websocket.receive()
            if "bytes" in msg and msg["bytes"]:
                data = msg["bytes"]
                if not header_bytes:
                    header_bytes = data[:4096]

                audio_buffer.write(data)
                curr_size = audio_buffer.tell()

                if curr_size > MAX_BUFFER_BYTES:
                    audio_buffer = io.BytesIO()
                    audio_buffer.write(header_bytes)
                    audio_buffer.write(data)

                if not transcribe_lock.locked():
                    async with transcribe_lock:
                        payload_data = audio_buffer.getvalue()
                        partial = await _transcribe_bytes_async(payload_data)
                        if partial:
                            await websocket.send_json(
                                {
                                    "status": "transcribing",
                                    "text": partial,
                                    "finalized_text": finalized_text,
                                }
                            )

            elif "text" in msg and msg["text"]:
                txt = msg["text"]
                if txt == "FINAL":
                    async with transcribe_lock:
                        payload_data = audio_buffer.getvalue()
                        partial = await _transcribe_bytes_async(payload_data)
                        if partial:
                            finalized_text += " " + partial
                        await websocket.send_json(
                            {
                                "status": "completed",
                                "text": "",
                                "finalized_text": finalized_text.strip(),
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
