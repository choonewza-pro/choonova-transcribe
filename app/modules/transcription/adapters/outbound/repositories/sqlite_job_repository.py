"""
SQLite implementation of JobRepositoryPort for Transcription jobs.
"""

from typing import Optional, List
from app.core.db import get_db_connection
from app.modules.transcription.domain.entities import TranscriptionJob
from app.modules.transcription.domain.ports import JobRepositoryPort


def _row_to_job(r) -> TranscriptionJob:
    return TranscriptionJob(
        job_id=r["job_id"],
        filename=r["filename"],
        file_size_bytes=r["file_size_bytes"],
        language=r["language"] if "language" in r.keys() else "th",
        status=r["status"],
        progress_pct=r["progress_pct"],
        current_stage=r["current_stage"],
        total_chunks=r["total_chunks"],
        completed_chunks=r["completed_chunks"],
        duration_seconds=r["duration_seconds"],
        elapsed_seconds=r["elapsed_seconds"],
        result_text=r["result_text"],
        timestamps_json=r["timestamps_json"],
        srt_text=r["srt_text"],
        error_message=r["error_message"],
        created_at=str(r["created_at"]) if r["created_at"] else None,
        updated_at=str(r["updated_at"]) if r["updated_at"] else None,
    )


class SQLiteJobRepository(JobRepositoryPort):

    def create_job(self, job: TranscriptionJob) -> TranscriptionJob:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    job_id, filename, file_size_bytes, language, status,
                    progress_pct, current_stage, total_chunks, completed_chunks,
                    duration_seconds, elapsed_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id, job.filename, job.file_size_bytes, job.language,
                    job.status, job.progress_pct, job.current_stage,
                    job.total_chunks, job.completed_chunks,
                    job.duration_seconds, job.elapsed_seconds,
                ),
            )
            conn.commit()
        return self.get_job(job.job_id)

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return _row_to_job(row)
        return None

    def update_progress(self, job_id: str, progress_pct: float, current_stage: str, completed_chunks: int, elapsed_seconds: float) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET progress_pct = ?, current_stage = ?, completed_chunks = ?, elapsed_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (progress_pct, current_stage, completed_chunks, elapsed_seconds, job_id),
            )
            conn.commit()

    def complete_job(self, job_id: str, result_text: str, timestamps_json: str, srt_text: str, elapsed_seconds: float) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'completed', progress_pct = 100.0, current_stage = 'done',
                    result_text = ?, timestamps_json = ?, srt_text = ?, elapsed_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (result_text, timestamps_json, srt_text, elapsed_seconds, job_id),
            )
            conn.commit()

    def fail_job(self, job_id: str, error_message: str) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'failed', current_stage = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (error_message, job_id),
            )
            conn.commit()

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[TranscriptionJob]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [_row_to_job(r) for r in cursor.fetchall()]

    def delete_job(self, job_id: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0
