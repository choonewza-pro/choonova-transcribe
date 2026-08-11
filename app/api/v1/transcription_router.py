"""
API Router for Long-form ASR Transcription jobs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import verify_api_key
from app.modules.transcription.adapters.outbound.repositories.sqlite_job_repository import SQLiteJobRepository
from app.modules.transcription.application.transcription_service import TranscriptionService

router = APIRouter(prefix="/v1/transcribe", tags=["Transcription"])


def get_transcription_service() -> TranscriptionService:
    repo = SQLiteJobRepository()
    return TranscriptionService(repo)


class JobResponse(BaseModel):
    job_id: str
    filename: str
    language: str
    status: str
    progress_pct: float
    current_stage: str
    result_text: str | None = None
    srt_text: str | None = None
    error_message: str | None = None


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_transcription_job(
    job_id: str,
    authenticated: bool = Depends(verify_api_key),
    service: TranscriptionService = Depends(get_transcription_service),
):
    """Get transcription job details by ID."""
    job = service.get_job(job_id)
    return JobResponse(
        job_id=job.job_id,
        filename=job.filename,
        language=job.language,
        status=job.status,
        progress_pct=job.progress_pct,
        current_stage=job.current_stage,
        result_text=job.result_text,
        srt_text=job.srt_text,
        error_message=job.error_message,
    )


@router.delete("/jobs/{job_id}")
async def delete_transcription_job(
    job_id: str,
    authenticated: bool = Depends(verify_api_key),
    service: TranscriptionService = Depends(get_transcription_service),
):
    """Delete a transcription job record."""
    deleted = service.delete_job(job_id)
    return {"status": "success", "job_id": job_id, "deleted": deleted}
