"""
UI Dashboard Web Views Router.
Renders HTML templates for the frontend interface.
"""

import os
import hmac
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import (
    BASE_DIR,
    MAX_AUDIO_UPLOAD_SIZE_MB,
    MAX_UPLOAD_SIZE_MB,
    COMPRESS_CRF,
    COMPRESS_PRESET,
    COMPRESS_ENCODER,
    DEVICE,
    COMPRESS_MAX_CONCURRENT,
    COMPRESS_MAX_QUEUED,
    TRANSCRIBE_MAX_CONCURRENT,
    TRANSCRIBE_MAX_QUEUED,
    MAX_MEDIA_DURATION_SEC,
    GATEWAY_API_KEY,
    GATEWAY_API_KEY_IS_DEFAULT,
    ALLOW_ACCESS_TRANSCRIBE_HISTORY,
    ALLOW_ACCESS_COMPRESS_HISTORY,
)

router = APIRouter(tags=["Web Views"])
templates_dir = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=templates_dir)


def _compress_retention_summary() -> dict:
    from app.modules.compression.adapters.outbound.repositories.sqlite_compress_repository import SQLiteCompressRepository
    from app.modules.compression.application.compression_service import CompressionService
    svc = CompressionService(SQLiteCompressRepository())
    return svc.get_retention_summary()


def check_history_access(request: Request, history_type: str) -> tuple[bool, str | None]:
    """
    Checks if the user is allowed to access the history page.
    Returns (is_allowed, verified_api_key_to_set_in_cookie)
    """
    # 1. Check bypass flag
    if history_type == "transcribe" and ALLOW_ACCESS_TRANSCRIBE_HISTORY:
        return True, None
    if history_type == "compress" and ALLOW_ACCESS_COMPRESS_HISTORY:
        return True, None

    # 2. Check API Key from query params, headers, or cookies
    api_key = request.query_params.get("api_key") or request.query_params.get("x-api-key")
    if not api_key:
        api_key = request.headers.get("x-api-key")
    if not api_key:
        api_key = request.cookies.get("typhoon_asr_api_key") or request.cookies.get("api_key")

    if not api_key:
        return False, None

    token = api_key.strip()
    if hmac.compare_digest(token, GATEWAY_API_KEY):
        return True, token

    return False, None


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "max_audio_upload_mb": MAX_AUDIO_UPLOAD_SIZE_MB,
            "max_media_duration_sec": MAX_MEDIA_DURATION_SEC,
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
            "allow_access_transcribe_history": ALLOW_ACCESS_TRANSCRIBE_HISTORY,
            "allow_access_compress_history": ALLOW_ACCESS_COMPRESS_HISTORY,
            "using_default_api_key": GATEWAY_API_KEY_IS_DEFAULT,
        },
    )


@router.get("/audio/transcribe", response_class=HTMLResponse)
async def audio_transcribe_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"max_audio_upload_mb": MAX_AUDIO_UPLOAD_SIZE_MB},
    )


@router.get("/realtime/stream", response_class=HTMLResponse)
async def realtime_stream_page(request: Request):
    return templates.TemplateResponse(request=request, name="realtime.html")


@router.get("/media/transcribe", response_class=HTMLResponse)
async def media_transcribe_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="media.html",
        context={
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
            "max_media_duration_sec": MAX_MEDIA_DURATION_SEC,
            "max_concurrent": TRANSCRIBE_MAX_CONCURRENT,
            "max_queued": TRANSCRIBE_MAX_QUEUED,
        },
    )


@router.get("/media/compress", response_class=HTMLResponse)
async def media_compress_page(request: Request):
    retention = _compress_retention_summary()
    return templates.TemplateResponse(
        request=request,
        name="compress.html",
        context={
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
            "max_media_duration_sec": MAX_MEDIA_DURATION_SEC,
            "default_crf": COMPRESS_CRF,
            "default_preset": COMPRESS_PRESET,
            "encoder": COMPRESS_ENCODER,
            "device": DEVICE,
            "max_concurrent": COMPRESS_MAX_CONCURRENT,
            "max_queued": COMPRESS_MAX_QUEUED,
            "retention_hours": retention.get("retention_hours", 24),
            "last_cleanup_at": retention.get("last_cleanup_at"),
            "last_cleanup_count": retention.get("last_cleanup_count", 0),
        },
    )


@router.get("/media/compress/jobs/history", response_class=HTMLResponse)
async def compress_jobs_history_page(request: Request):
    is_allowed, api_key = check_history_access(request, "compress")
    if not is_allowed:
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "error_message": "ไม่พบ API Key หรือ API Key ของคุณไม่ถูกต้อง",
                "active_page": "compress_jobs",
            },
            status_code=401,
        )

    retention = _compress_retention_summary()
    response = templates.TemplateResponse(
        request=request,
        name="compress_jobs.html",
        context={
            "active_page": "compress_jobs",
            "header_badge": "Compressor History",
            "retention_hours": retention.get("retention_hours", 24),
            "last_cleanup_at": retention.get("last_cleanup_at"),
            "last_cleanup_count": retention.get("last_cleanup_count", 0),
            "allow_access_compress_history": ALLOW_ACCESS_COMPRESS_HISTORY,
        },
    )
    if api_key:
        response.set_cookie(
            key="typhoon_asr_api_key",
            value=api_key,
            max_age=31536000,
            path="/",
            samesite="lax",
        )
    return response


@router.get("/media/transcribe/jobs/history", response_class=HTMLResponse)
async def jobs_history_page(request: Request):
    is_allowed, api_key = check_history_access(request, "transcribe")
    if not is_allowed:
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "error_message": "ไม่พบ API Key หรือ API Key ของคุณไม่ถูกต้อง",
                "active_page": "jobs",
            },
            status_code=401,
        )

    response = templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
            "max_media_duration_sec": MAX_MEDIA_DURATION_SEC,
            "allow_access_transcribe_history": ALLOW_ACCESS_TRANSCRIBE_HISTORY,
        },
    )
    if api_key:
        response.set_cookie(
            key="typhoon_asr_api_key",
            value=api_key,
            max_age=31536000,
            path="/",
            samesite="lax",
        )
    return response


@router.get("/setting", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="setting.html",
        context={"using_default_api_key": GATEWAY_API_KEY_IS_DEFAULT},
    )


@router.get("/test", response_class=HTMLResponse)
async def api_test_page(request: Request):
    api_key = request.query_params.get("api_key") or request.query_params.get("x-api-key")
    if not api_key:
        api_key = request.headers.get("x-api-key")
    if not api_key:
        api_key = request.cookies.get("typhoon_asr_api_key") or request.cookies.get("api_key")

    if not api_key or not hmac.compare_digest(api_key.strip(), GATEWAY_API_KEY):
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "error_message": "ต้องตั้งค่า GATEWAY_API_KEY ก่อนจึงจะเข้าใช้งานหน้าทดสอบได้ — ไปที่หน้า ตั้งค่า แล้วกรอก API Key",
                "active_page": "apitest",
                "page_title": "หน้าทดสอบ API",
            },
            status_code=401,
        )
    return templates.TemplateResponse(request=request, name="apitest.html")


@router.get("/jobs/history", response_class=HTMLResponse)
async def jobs_history_page_legacy(request: Request):
    return RedirectResponse(url="/media/transcribe/jobs/history", status_code=302)
