"""
UI Dashboard Web Views Router.
Renders HTML templates for the frontend interface.
"""

import os
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
)

router = APIRouter(tags=["Web Views"])
templates_dir = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=templates_dir)


def _compress_retention_summary() -> dict:
    from app.db import get_compress_retention_summary
    return get_compress_retention_summary()


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"max_audio_upload_mb": MAX_AUDIO_UPLOAD_SIZE_MB},
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
        context={"max_upload_mb": MAX_UPLOAD_SIZE_MB},
    )


@router.get("/media/compress", response_class=HTMLResponse)
async def media_compress_page(request: Request):
    retention = _compress_retention_summary()
    return templates.TemplateResponse(
        request=request,
        name="compress.html",
        context={
            "max_upload_mb": MAX_UPLOAD_SIZE_MB,
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
    retention = _compress_retention_summary()
    return templates.TemplateResponse(
        request=request,
        name="compress_jobs.html",
        context={
            "active_page": "compress_jobs",
            "header_badge": "Compressor History",
            "retention_hours": retention.get("retention_hours", 24),
            "last_cleanup_at": retention.get("last_cleanup_at"),
            "last_cleanup_count": retention.get("last_cleanup_count", 0),
        },
    )


@router.get("/media/transcribe/jobs/history", response_class=HTMLResponse)
async def jobs_history_page(request: Request):
    return templates.TemplateResponse(request=request, name="jobs.html")


@router.get("/setting", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="setting.html")


@router.get("/jobs/history", response_class=HTMLResponse)
async def jobs_history_page_legacy(request: Request):
    return RedirectResponse(url="/media/transcribe/jobs/history", status_code=302)
