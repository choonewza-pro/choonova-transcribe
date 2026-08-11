"""
API Router for Video Compression endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.modules.compression.adapters.outbound.repositories.sqlite_compress_repository import SQLiteCompressRepository
from app.modules.compression.application.compression_service import CompressionService

router = APIRouter(prefix="/v1/compress", tags=["Compression"])


def get_compression_service() -> CompressionService:
    repo = SQLiteCompressRepository()
    return CompressionService(repo)


class CompressJobResponse(BaseModel):
    job_id: str
    filename: str
    status: str
    progress_pct: float
    current_stage: str
    output_path: str | None = None
    compression_ratio: float | None = None
    error_message: str | None = None


@router.get("/jobs/{job_id}", response_model=CompressJobResponse)
async def get_compress_job(
    job_id: str,
    authenticated: bool = Depends(verify_api_key),
    service: CompressionService = Depends(get_compression_service),
):
    """Retrieve compression job details by ID."""
    job = service.get_job(job_id)
    return CompressJobResponse(
        job_id=job.job_id,
        filename=job.filename,
        status=job.status,
        progress_pct=job.progress_pct,
        current_stage=job.current_stage,
        output_path=job.output_path,
        compression_ratio=job.compression_ratio,
        error_message=job.error_message,
    )


@router.delete("/jobs/{job_id}")
async def delete_compress_job(
    job_id: str,
    authenticated: bool = Depends(verify_api_key),
    service: CompressionService = Depends(get_compression_service),
):
    """Delete a compression job record and associated output files."""
    deleted = service.delete_job(job_id)
    return {"status": "success", "job_id": job_id, "deleted": deleted}
