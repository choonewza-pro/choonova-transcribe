"""
API Endpoint Self-Test Router.

POST /v1/tests/run  — runs the automated endpoint self-test and streams the
                      results as application/x-ndjson (one JSON object per
                      line: test results, live progress, and a final summary).
GET  /v1/tests/info  — asset availability + current defaults (for the page).

Requires a valid x-api-key (same GATEWAY_API_KEY consumers use). Only one
self-test run may be active at a time (HTTP 409 otherwise).
"""

import asyncio
import contextlib
import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import (
    APITEST_COMPRESS_MAX_WAIT_SEC,
    APITEST_POLL_INTERVAL_SEC,
    APITEST_TRANSCRIBE_MAX_WAIT_SEC,
    COMPRESS_CRF,
    COMPRESS_ENCODER,
    COMPRESS_PRESET,
    GATEWAY_API_KEY,
    PORT,
    SERVICE_DIR,
)
from app.core.security import verify_api_key
from app.modules.apitest.adapters.outbound.self_http_client import HttpxSelfClient
from app.modules.apitest.application.apitest_runner import (
    ApiTestRunner,
    AssetNotFoundError,
)

router = APIRouter(prefix="/v1/tests", tags=["Endpoint Self-Test"])

ASSETS_DIR = os.path.join(SERVICE_DIR, "assets")

_run_in_progress = False


def _build_runner() -> ApiTestRunner:
    http = HttpxSelfClient(
        base_url=f"http://127.0.0.1:{PORT}",
        api_key=GATEWAY_API_KEY,
        timeout=60.0,
    )
    return ApiTestRunner(http=http, assets_dir=ASSETS_DIR, api_key=GATEWAY_API_KEY)


@router.get("/info")
async def tests_info(authenticated: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """Current self-test configuration and the availability of sample assets."""
    runner = _build_runner()
    info = runner.asset_info()
    info["defaults"] = {
        "crf": COMPRESS_CRF,
        "preset": COMPRESS_PRESET,
        "encoder": COMPRESS_ENCODER,
        "language": "th",
    }
    info["limits"] = {
        "transcribe_max_wait_sec": APITEST_TRANSCRIBE_MAX_WAIT_SEC,
        "compress_max_wait_sec": APITEST_COMPRESS_MAX_WAIT_SEC,
        "poll_interval_sec": APITEST_POLL_INTERVAL_SEC,
    }
    info["suites"] = {
        "typhoon": {
            "name": "Typhoon ASR (มาตรฐาน)",
            "desc": "ทดสอบ ASR ภาษาไทย + การบีบอัดวิดีโอ (Baseline ไม่ต้องใช้ HF_TOKEN)",
            "engine": "Typhoon FastConformer 114M",
            "hf_token_required": False,
            "vram": "~1.0 GB",
        },
        "pyannote": {
            "name": "Typhoon + PyAnnote 3.1",
            "desc": "ทดสอบถอดเสียงภาษาไทยพร้อมระบุผู้พูด (Thai Diarization)",
            "engine": "Typhoon ASR + PyAnnote 3.1",
            "hf_token_required": True,
            "vram": "~2.5 GB",
        },
        "whisperx": {
            "name": "WhisperX Pipeline",
            "desc": "ทดสอบถอดเสียงภาษาอังกฤษ/Auto พร้อมจัดเรียงระดับคำและระบุผู้พูด",
            "engine": "Faster-Whisper + wav2vec2 Alignment + PyAnnote 3.1",
            "hf_token_required": True,
            "vram": "~3.5 GB",
        },
    }
    return info


@router.post("/run")
async def run_self_test(
    suite: str = "typhoon",
    cleanup: bool = True,
    authenticated: bool = Depends(verify_api_key),
) -> StreamingResponse:
    """Run the automated self-test and stream results as NDJSON lines."""
    global _run_in_progress
    if _run_in_progress:
        raise HTTPException(
            status_code=409,
            detail="มีงานทดสอบกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน (only one test run at a time)",
        )

    runner = _build_runner()
    try:
        runner.check_assets()
    except AssetNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _run_in_progress = True

    run_events: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()

    async def event_generator():
        render_task: Optional[asyncio.Task] = None
        try:
            async def _render() -> None:
                try:
                    async def on_test(test) -> None:
                        await run_events.put({"type": "test", "data": test.to_dict()})

                    async def on_progress(p: Dict[str, Any]) -> None:
                        await run_events.put({"type": "progress", "data": p})

                    async def on_start(total: int) -> None:
                        await run_events.put({"type": "start", "total": total})

                    report = await runner.run(
                        suite=suite,
                        cleanup=cleanup,
                        on_test=on_test,
                        on_progress=on_progress,
                        on_start=on_start,
                    )
                    await run_events.put({"type": "done", "summary": report.to_dict()})
                except Exception as e:  # noqa: BLE001
                    with contextlib.suppress(Exception):
                        await run_events.put({"type": "error", "data": {"message": str(e)}})
                    with contextlib.suppress(Exception):
                        await run_events.put({"type": "done", "summary": {"error": str(e)}})

            render_task = asyncio.create_task(_render())
            while True:
                item = await run_events.get()
                yield json.dumps(item, ensure_ascii=False) + "\n"
                if item.get("type") == "done":
                    break
            if render_task is not None:
                await render_task
        finally:
            if render_task is not None and not render_task.done():
                render_task.cancel()
                with contextlib.suppress(Exception):
                    await render_task
            global _run_in_progress
            _run_in_progress = False

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")