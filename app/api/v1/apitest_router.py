"""
API Endpoint Self-Test Router.

POST /v1/tests/run        — starts the automated endpoint self-test as a
                            detached background task and returns 202 with a
                            run_id immediately. Only one run may be active at
                            a time (HTTP 409 otherwise, including the active
                            run_id so the UI can switch to watching it).
GET  /v1/tests/info        — asset availability + current defaults (for the page).
GET  /v1/tests/runs        — recent self-test runs (history, newest first).
GET  /v1/tests/runs/active — the currently running run, if any.
GET  /v1/tests/runs/{id}   — a full snapshot of one run (live or finished).

Runs are owned by the server (not by the HTTP request that started them), so a
page refresh or browser disconnect never loses the run or its results: clients
poll the run snapshot endpoints to watch progress and review finished results.

Requires a valid x-api-key (same GATEWAY_API_KEY consumers use).
"""

import asyncio
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import (
    APITEST_POLL_INTERVAL_SEC,
    APITEST_TRANSCRIBE_MAX_WAIT_SEC,
    GATEWAY_API_KEY,
    PORT,
    SERVICE_DIR,
)
from app.core.security import verify_api_key
from app.modules.apitest.adapters.outbound.self_http_client import HttpxSelfClient
from app.modules.apitest.adapters.outbound.sqlite_self_test_status_repository import (
    SQLiteSelfTestStatusRepository,
)
from app.modules.apitest.application.apitest_runner import (
    ApiTestRunner,
    AssetNotFoundError,
)
from app.modules.apitest.application.run_registry import (
    RunState,
    run_registry,
)
from app.modules.apitest.domain.ports import SelfTestStatusRepository

router = APIRouter(prefix="/v1/tests", tags=["Endpoint Self-Test"])

ASSETS_DIR = os.path.join(SERVICE_DIR, "assets")


def _status_repo() -> SelfTestStatusRepository:
    return SQLiteSelfTestStatusRepository()


def _persist_suite_status(suite: str, report) -> None:
    """Persist pass/fail for the suite and every finished test card."""
    repo = _status_repo()
    repo.upsert_suite(suite, "passed" if report.overall_passed else "failed")
    for t in report.tests:
        repo.upsert_test(suite, t.order, t.name_th,
                         "passed" if t.passed else "failed")


def _persist_suite_failure(suite: str) -> None:
    _status_repo().upsert_suite(suite, "failed")


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
        "language": "th",
    }
    info["limits"] = {
        "transcribe_max_wait_sec": APITEST_TRANSCRIBE_MAX_WAIT_SEC,
        "poll_interval_sec": APITEST_POLL_INTERVAL_SEC,
    }
    info["suites"] = {
        "word-diar": {
            "name": "Word-level + ผู้พูด (Audio Job)",
            "desc": "ทดสอบ /v1/audio/transcribe/jobs แบบ word-level + ระบุผู้พูด (test-audio-th.wav) — Thai Whisper / WhisperX",
            "engine": "Thai Whisper / WhisperX + Diarization",
            "hf_token_required": True,
            "vram": "~2.5-3.5 GB",
        },
        "word-only": {
            "name": "Word-level เท่านั้น (Audio Job)",
            "desc": "ทดสอบ /v1/audio/transcribe/jobs แบบ word-level ไม่ระบุผู้พูด (test-audio-th.wav) — Thai Whisper / Faster Whisper",
            "engine": "Thai Whisper / Faster-Whisper large-v3-turbo",
            "hf_token_required": False,
            "vram": "~1.0-2.0 GB",
        },
        "no-word": {
            "name": "ไม่มี Word-level (Audio Job)",
            "desc": "ทดสอบ /v1/audio/transcribe/jobs แบบไม่มี word-level / ไม่ระบุผู้พูด (test-audio-th.wav) — Typhoon / Thai Whisper / Faster Whisper",
            "engine": "Typhoon / Thai Whisper / Faster-Whisper large-v3-turbo",
            "hf_token_required": False,
            "vram": "~1.0-2.0 GB",
        },
        "sync": {
            "name": "Sync /v1/audio/transcribe (Word-level)",
            "desc": "ทดสอบ /v1/audio/transcribe แบบรอผลทันที (test-audio-th.wav) — ตรวจฟิลด์ segments: word-level + ผู้พูด (Thai Whisper / Faster Whisper / Typhoon)",
            "engine": "Thai Whisper / Faster-Whisper large-v3-turbo / Typhoon",
            "hf_token_required": True,
            "vram": "~1.0-2.5 GB",
        },
    }
    repo = _status_repo()
    info["status"] = repo.get_suite_statuses()
    info["test_status"] = {
        suite: {
            str(t.test_order): {
                "status": t.status,
                "label": t.test_label,
                "updated_at": t.updated_at,
            }
            for t in repo.get_tests(suite).values()
        }
        for suite in info["suites"]
    }
    return info


async def _run_background(run_id: str, suite: str, cleanup: bool) -> None:
    """Execute one self-test run, recording results into the registry.

    Runs detached from the request that created it; a client disconnect can
    never cancel it. Always finishes the run (success or failure)."""
    runner = _build_runner()

    async def on_test(test) -> None:
        run_registry.record_test(run_id, test.to_dict())

    async def on_progress(p: Dict[str, Any]) -> None:
        run_registry.record_progress(run_id, p)

    async def on_start(total: int) -> None:
        run_registry.set_expected_total(run_id, total)

    try:
        report = await runner.run(
            suite=suite,
            cleanup=cleanup,
            on_test=on_test,
            on_progress=on_progress,
            on_start=on_start,
        )
        run_registry.finish(run_id, summary=report.to_dict())
        _persist_suite_status(suite, report)
    except Exception as e:  # noqa: BLE001
        run_registry.finish(run_id, error=str(e))
        _persist_suite_failure(suite)


@router.post("/run", status_code=202)
async def run_self_test(
    suite: str = "no-word",
    cleanup: bool = True,
    authenticated: bool = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Start the automated self-test in the background and return a run_id."""
    active = run_registry.active_run()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "มีงานทดสอบกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน (only one test run at a time)",
                "active_run_id": active.run_id,
                "active_suite": active.suite,
            },
        )

    runner = _build_runner()
    try:
        runner.check_assets()
    except AssetNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    run_id = str(uuid.uuid4())
    run_registry.start(run_id=run_id, suite=suite, cleanup=cleanup)
    asyncio.create_task(_run_background(run_id, suite, cleanup))

    return {"run_id": run_id, "suite": suite, "status": "running"}


@router.get("/runs")
async def list_runs(authenticated: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """Recent self-test runs, newest first."""
    return {"runs": [r.to_dict() for r in run_registry.list()]}


@router.get("/runs/active")
async def active_run(authenticated: bool = Depends(verify_api_key)) -> Dict[str, Any]:
    """The currently running self-test run, if any."""
    state: Optional[RunState] = run_registry.active_run()
    if state is None:
        return {"active": False, "run": None}
    return {"active": True, "run": state.to_dict()}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str, authenticated: bool = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Full snapshot of one self-test run (live or finished)."""
    state = run_registry.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"ไม่พบงานทดสอบ: {run_id}")
    return state.to_dict()