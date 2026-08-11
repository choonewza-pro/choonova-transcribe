"""
SQLite implementation of CompressionRepositoryPort.
"""

from typing import Optional, List
from app.core.db import get_db_connection
from app.modules.compression.domain.entities import CompressionJob
from app.modules.compression.domain.ports import CompressionRepositoryPort


def _row_to_job(r) -> CompressionJob:
    return CompressionJob(
        job_id=r["job_id"],
        filename=r["filename"],
        input_path=r["input_path"],
        file_size_bytes=r["file_size_bytes"],
        status=r["status"],
        progress_pct=r["progress_pct"],
        current_stage=r["current_stage"],
        duration_seconds=r["duration_seconds"],
        elapsed_seconds=r["elapsed_seconds"],
        output_path=r["output_path"],
        output_size_bytes=r["output_size_bytes"],
        compression_ratio=r["compression_ratio"],
        video_codec=r["video_codec"],
        audio_codec=r["audio_codec"],
        resolution=r["resolution"],
        bitrate_kbps=r["bitrate_kbps"],
        fps=r["fps"],
        encoder_used=r["encoder_used"],
        error_message=r["error_message"],
        created_at=str(r["created_at"]) if r["created_at"] else None,
        updated_at=str(r["updated_at"]) if r["updated_at"] else None,
    )


class SQLiteCompressRepository(CompressionRepositoryPort):

    def create_job(self, job: CompressionJob) -> CompressionJob:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO compress_jobs (
                    job_id, filename, input_path, file_size_bytes, status,
                    progress_pct, current_stage, duration_seconds, elapsed_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id, job.filename, job.input_path, job.file_size_bytes,
                    job.status, job.progress_pct, job.current_stage,
                    job.duration_seconds, job.elapsed_seconds,
                ),
            )
            conn.commit()
        return self.get_job(job.job_id)

    def get_job(self, job_id: str) -> Optional[CompressionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM compress_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return _row_to_job(row)
        return None

    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, elapsed_seconds: float) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET progress_pct = ?, current_stage = ?, elapsed_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (progress_pct, current_stage, elapsed_seconds, job_id),
            )
            conn.commit()

    def complete_job(self, job_id: str, output_path: str, output_size_bytes: int, compression_ratio: float, encoder_used: str, elapsed_seconds: float) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET status = 'completed', progress_pct = 100.0, current_stage = 'done',
                    output_path = ?, output_size_bytes = ?, compression_ratio = ?,
                    encoder_used = ?, elapsed_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (output_path, output_size_bytes, compression_ratio, encoder_used, elapsed_seconds, job_id),
            )
            conn.commit()

    def fail_job(self, job_id: str, error_message: str) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE compress_jobs
                SET status = 'failed', current_stage = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (error_message, job_id),
            )
            conn.commit()

    def get_queued_jobs(self, limit: int = 10) -> List[CompressionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM compress_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            return [_row_to_job(r) for r in cursor.fetchall()]

    def delete_job(self, job_id: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM compress_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0
